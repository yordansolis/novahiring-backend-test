"""CV evaluation pipeline: KO screening + AI dimension scoring for uploaded CVs."""
import json
import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import CandidateProfile, DiscoveryJSON, DimensionScore
from models.candidate import Candidate
from models.evaluation import DimensionScoreRecord, Evaluation
from models.job import JobOpening
from services.ai_client import AIClient, ScoreRangeValidator
from services.ko_checker import KOChecker
from services.notification_service import NotificationService
from services.profile import ProfileBuilder
from services.scorer import Scorer

logger = logging.getLogger("nova.cv_evaluator")


class CVEvaluator:
    def __init__(
        self,
        db: AsyncSession,
        ai_client: AIClient,
        scorer: Scorer,
        notification_service: NotificationService,
    ) -> None:
        self._db = db
        self._ai = ai_client
        self._scorer = scorer
        self._notifier = notification_service

    async def evaluate_job_candidates(self, job_id: str) -> list[str]:
        """Evaluate all candidates for job_id that have no existing Evaluation.
        Returns the list of APTO candidate_ids."""
        job = await self._db.get(JobOpening, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        discovery = DiscoveryJSON(**job.discovery_json)

        # Candidates with no Evaluation for this job
        evaluated_sub = select(Evaluation.candidate_id).where(Evaluation.job_id == job_id)
        result = await self._db.execute(
            select(Candidate).where(
                Candidate.job_id == job_id,
                Candidate.id.notin_(evaluated_sub),
                Candidate.cv_text.isnot(None),
            )
        )
        candidates = result.scalars().all()

        apto_ids: list[str] = []
        request_id = str(uuid.uuid4())

        for candidate in candidates:
            try:
                is_apto = await self._evaluate_candidate(
                    candidate, job_id, discovery, request_id
                )
                if is_apto:
                    apto_ids.append(candidate.id)
            except Exception:
                logger.exception("Error evaluating candidate %s", candidate.id)

        return apto_ids

    async def _evaluate_candidate(
        self,
        candidate: Candidate,
        job_id: str,
        discovery: DiscoveryJSON,
        request_id: str,
    ) -> bool:
        profile = self._build_profile(candidate, job_id, discovery)
        passed_ko, first_failing_ko = KOChecker().apply(profile)
        ko_results_raw = [r.model_dump() for r in profile.ko_screen_results]

        if not passed_ko:
            evaluation = Evaluation(
                job_id=job_id,
                candidate_id=candidate.id,
                passed_ko=False,
                first_failing_ko=first_failing_ko,
                weighted_score=None,
                normalized_score=None,
                resultado="DESCARTADO",
                ko_results=ko_results_raw,
            )
            self._db.add(evaluation)
            candidate.passed_ko = False
            await self._db.commit()
            logger.info("Candidate %s DESCARTADO (%s)", candidate.id, first_failing_ko)
            return False

        dimension_scores = await self._score_dimensions(candidate, discovery, request_id)
        weighted_score, normalized_score = self._scorer.calculate(dimension_scores, discovery)

        eval_id = str(uuid.uuid4())
        evaluation = Evaluation(
            id=eval_id,
            job_id=job_id,
            candidate_id=candidate.id,
            passed_ko=True,
            first_failing_ko=None,
            weighted_score=weighted_score,
            normalized_score=normalized_score,
            resultado="APTO",
            ko_results=ko_results_raw,
        )
        self._db.add(evaluation)

        for dim_score in dimension_scores:
            self._db.add(DimensionScoreRecord(
                evaluation_id=eval_id,
                candidate_id=candidate.id,
                job_id=job_id,
                dimension_id=dim_score.dimension_id,
                raw_score=dim_score.score,
                peso=dim_score.peso,
                justificacion=dim_score.justificacion,
                evidencia=dim_score.evidencia,
            ))

        candidate.passed_ko = True
        await self._db.flush()

        await self._notifier.send_interview_invitation(candidate, job_id)
        await self._db.commit()

        logger.info(
            "Candidate %s APTO score=%.2f",
            candidate.id,
            float(weighted_score),
        )
        return True

    def _build_profile(
        self,
        candidate: Candidate,
        job_id: str,
        discovery: DiscoveryJSON,
    ) -> CandidateProfile:
        if candidate.profile_json:
            try:
                return CandidateProfile(**candidate.profile_json)
            except Exception:
                pass
        return ProfileBuilder().build(
            candidate_id=candidate.id,
            job_id=job_id,
            cv_text=candidate.cv_text or "",
            discovery=discovery,
        )

    async def _score_dimensions(
        self,
        candidate: Candidate,
        discovery: DiscoveryJSON,
        request_id: str,
    ) -> list[DimensionScore]:
        scores: list[DimensionScore] = []
        for dim in discovery.dimensions:
            raw = await self._ai.call(
                prompt_name="cv_dimension_evaluator",
                template_vars={
                    "dimension_id": dim.id,
                    "dimension_name": dim.nombre,
                    "rubric_5": dim.rubricas.get("5", ""),
                    "rubric_3": dim.rubricas.get("3", ""),
                    "rubric_1": dim.rubricas.get("1", ""),
                    "candidate_cv": candidate.cv_text or "",
                },
                conversation_history=[],
                session_id=None,
                request_id=request_id,
                validator=ScoreRangeValidator(),
            )
            parsed = json.loads(raw)
            scores.append(DimensionScore(
                dimension_id=dim.id,
                peso=dim.peso,
                score=Decimal(str(parsed["score"])),
                justificacion=parsed.get("justificacion", ""),
                evidencia=parsed.get("evidencia", ""),
            ))
        return scores
