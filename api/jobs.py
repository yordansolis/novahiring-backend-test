from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import DiscoveryJSON
from database import get_db
from models.evaluation import Evaluation
from models.job import JobOpening
from services.report_writer import ReportWriter

router = APIRouter()


@router.get("/{job_id}/offer")
async def get_job_offer(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "title": job.title, "offer_text": job.offer_text}


@router.get("/{job_id}/profile")
async def get_candidate_profile(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    discovery = DiscoveryJSON(**job.discovery_json)
    return {
        "required_skills": discovery.perfil_candidato["habilidades_tecnicas"]["obligatorias"],
        "ko_criteria": [k.model_dump() for k in discovery.ko_criteria],
        "scorecard": [d.model_dump() for d in discovery.dimensions],
        "total_weight": discovery.total_weight,
    }


@router.get("/{job_id}/ranking")
async def get_ranking(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Evaluation)
        .where(Evaluation.job_id == job_id)
        .order_by(Evaluation.passed_ko.desc(), Evaluation.weighted_score.desc())
    )
    evaluations = result.scalars().all()
    return {"candidates": [e.to_summary() for e in evaluations]}


@router.get("/{job_id}/report", response_class=PlainTextResponse)
async def get_report(job_id: str, db: AsyncSession = Depends(get_db)):
    """Returns the final selection report in Markdown format."""
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report = await ReportWriter().generate(job_id, db)
    return PlainTextResponse(content=report, media_type="text/markdown; charset=utf-8")
