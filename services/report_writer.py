"""Generates the final markdown ranking report from DB evaluations."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.candidate import Candidate
from models.evaluation import DimensionScoreRecord, Evaluation
from models.job import JobOpening


class ReportWriter:
    async def generate(self, job_id: str, db: AsyncSession) -> str:
        job = await db.get(JobOpening, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        discovery = job.discovery_json or {}
        empresa = discovery.get("cliente", {}).get("nombre", "Cliente")
        scorecard = discovery.get("scorecard", {})
        dimensions = {d["id"]: d for d in scorecard.get("dimensiones", [])}
        total_weight = scorecard.get("peso_total", 19)
        ko_criteria = {
            kc["id"]: kc
            for kc in discovery.get("perfil_candidato", {}).get("criterios_de_descarte", [])
        }

        # Load all evaluations, take the latest per candidate
        evals_result = await db.execute(
            select(Evaluation).where(Evaluation.job_id == job_id)
        )
        all_evals = evals_result.scalars().all()
        if not all_evals:
            return f"# Informe — {empresa}\n\nNo hay evaluaciones para este puesto.\n"

        by_candidate: dict[str, list[Evaluation]] = defaultdict(list)
        for ev in all_evals:
            by_candidate[ev.candidate_id].append(ev)

        latest_evals = [
            sorted(evs, key=lambda e: e.created_at, reverse=True)[0]
            for evs in by_candidate.values()
        ]

        # Load candidates
        cand_ids = [e.candidate_id for e in latest_evals]
        cands_result = await db.execute(
            select(Candidate).where(Candidate.id.in_(cand_ids))
        )
        candidates = {c.id: c for c in cands_result.scalars().all()}

        aptos = sorted(
            [e for e in latest_evals if e.passed_ko],
            key=lambda e: e.weighted_score or Decimal("0"),
            reverse=True,
        )
        descartados = [e for e in latest_evals if not e.passed_ko]

        # Load dimension scores for APTO evaluations
        apto_eval_ids = [e.id for e in aptos]
        dim_scores_by_eval: dict[str, list[DimensionScoreRecord]] = defaultdict(list)
        if apto_eval_ids:
            ds_result = await db.execute(
                select(DimensionScoreRecord).where(
                    DimensionScoreRecord.evaluation_id.in_(apto_eval_ids)
                )
            )
            for ds in ds_result.scalars().all():
                dim_scores_by_eval[ds.evaluation_id].append(ds)

        lines: list[str] = []
        fecha = datetime.utcnow().strftime("%d/%m/%Y")

        # ── Header ────────────────────────────────────────────────────────────
        lines += [
            f"# Informe de Selección — {empresa}",
            "",
            f"**Puesto:** {job.title}  ",
            f"**Fecha:** {fecha}  ",
            f"**Evaluados:** {len(aptos)} APTOS · {len(descartados)} DESCARTADOS",
            "",
        ]

        # ── Ranking table ─────────────────────────────────────────────────────
        medals = ["🥇", "🥈", "🥉"]
        lines += [
            "## Ranking Final",
            "",
            "| # | Candidato | Score | % | Resultado |",
            "|---|-----------|-------|---|-----------|",
        ]
        for i, ev in enumerate(aptos):
            cand = candidates.get(ev.candidate_id)
            nombre = cand.nombre if cand else ev.candidate_id
            medal = medals[i] if i < len(medals) else str(i + 1)
            score = float(ev.weighted_score or 0)
            pct = float(ev.normalized_score or 0) * 100
            lines.append(f"| {medal} | {nombre} | {score:.2f}/5 | {pct:.1f}% | {ev.resultado} |")
        lines.append("")

        # ── Recommended candidate ─────────────────────────────────────────────
        if aptos:
            winner = aptos[0]
            w_cand = candidates.get(winner.candidate_id)
            w_name = w_cand.nombre if w_cand else winner.candidate_id
            w_score = float(winner.weighted_score or 0)
            lines += [
                "## Candidato Recomendado",
                "",
                f"**{w_name}** lidera el ranking con **{w_score:.2f}/5** "
                f"({float(winner.normalized_score or 0)*100:.1f}%).",
            ]
            if len(aptos) > 1:
                runner = aptos[1]
                r_cand = candidates.get(runner.candidate_id)
                r_name = r_cand.nombre if r_cand else runner.candidate_id
                gap = w_score - float(runner.weighted_score or 0)
                lines.append(f"Ventaja sobre {r_name}: **+{gap:.2f} puntos**.")
            lines.append("")

        # ── Detailed evaluations ──────────────────────────────────────────────
        lines += ["## Evaluaciones Detalladas", ""]
        for i, ev in enumerate(aptos):
            cand = candidates.get(ev.candidate_id)
            nombre = cand.nombre if cand else ev.candidate_id
            score = float(ev.weighted_score or 0)
            medal = medals[i] if i < len(medals) else f"#{i+1}"

            lines += [
                f"### {medal} {nombre} — {score:.2f}/5 ({ev.resultado})",
                "",
                "| Dimensión | Score | Peso | Justificación |",
                "|-----------|-------|------|---------------|",
            ]
            for ds in sorted(dim_scores_by_eval.get(ev.id, []), key=lambda d: d.dimension_id):
                dim_name = dimensions.get(ds.dimension_id, {}).get("nombre", ds.dimension_id)
                justif = ds.justificacion or ""
                if len(justif) > 80:
                    justif = justif[:77] + "..."
                lines.append(
                    f"| **{ds.dimension_id}** {dim_name} | {float(ds.raw_score):.0f}/5 | ×{ds.peso} | {justif} |"
                )
            lines += [
                "",
                f"*Σ(score × peso) / {total_weight} = {score:.2f}/5*",
                "",
            ]

        # ── Descartados ───────────────────────────────────────────────────────
        if descartados:
            lines += [
                "## Candidatos Descartados",
                "",
                "| Candidato | KO | Criterio |",
                "|-----------|-----|---------|",
            ]
            for ev in descartados:
                cand = candidates.get(ev.candidate_id)
                nombre = cand.nombre if cand else ev.candidate_id
                ko_id = ev.first_failing_ko or "—"
                ko_desc = ko_criteria.get(ko_id, {}).get("descripcion", "—")
                lines.append(f"| {nombre} | {ko_id} | {ko_desc} |")
            lines.append("")

        lines += ["---", "*Generado por NovaHiring*", ""]
        return "\n".join(lines)
