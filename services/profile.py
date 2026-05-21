import hashlib

from contracts import CandidateProfile, DiscoveryJSON, KOCriterion, KOScreenResult

PROFILE_ALGORITHM_VERSION = "1.0.0"


class ProfileBuilder:
    """
    Python puro. CV texto + DiscoveryJSON → CandidateProfile.
    Mismo input siempre produce mismo output. Cero IA.
    """

    def build(
        self,
        candidate_id: str,
        job_id: str,
        cv_text: str,
        discovery: DiscoveryJSON,
        ko_results_override: list[dict] | None = None,
    ) -> CandidateProfile:
        cv_lower = cv_text.lower()
        cv_sha256 = hashlib.sha256(cv_text.encode()).hexdigest()

        if ko_results_override is not None:
            ko_screen_results = [
                KOScreenResult(
                    ko_id=r["id"],
                    resultado=r["resultado"],
                    passed=r["resultado"] == "PASA",
                    evidencia=r.get("evidencia", ""),
                )
                for r in ko_results_override
            ]
        else:
            ko_screen_results = [self._evaluate_ko(ko, cv_lower) for ko in discovery.ko_criteria]

        required = discovery.perfil_candidato["habilidades_tecnicas"]["obligatorias"]
        matched = [s for s in required if s.replace("_", " ") in cv_lower or s in cv_lower]
        missing = [s for s in required if s not in matched]

        return CandidateProfile(
            candidate_id=candidate_id,
            job_id=job_id,
            ko_screen_results=ko_screen_results,
            passed_ko_screen=all(r.passed for r in ko_screen_results),
            matched_required_skills=matched,
            missing_required_skills=missing,
            cv_sha256=cv_sha256,
            profile_algorithm_version=PROFILE_ALGORITHM_VERSION,
        )

    def _evaluate_ko(self, ko: KOCriterion, cv_lower: str) -> KOScreenResult:
        ko_keywords: dict[str, list[str]] = {
            "KO1": ["whatsapp business api", "whatsapp business", "meta cloud api", "twilio whatsapp"],
            "KO2": ["rgpd", "lopdgdd", "gdpr", "protección de datos", "datos sanitarios", "aepd"],
            "KO3": ["sin supervisión", "autonomía", "en solitario", "decisiones arquitectónicas"],
        }
        keywords = ko_keywords.get(ko.id, [])
        found = any(kw in cv_lower for kw in keywords)
        return KOScreenResult(
            ko_id=ko.id,
            resultado="PASA" if found else "FALLA",
            passed=found,
            evidencia=f"Keyword heuristic: {'found' if found else 'not found'} in CV.",
        )
