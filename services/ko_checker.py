from contracts import CandidateProfile


class KOChecker:
    """
    Lee los KOScreenResult del perfil y retorna (passed, primer_ko_que_falla).
    Primer KO que falla corta la evaluación. Nunca llama a la IA.
    """

    def apply(self, profile: CandidateProfile) -> tuple[bool, str | None]:
        for result in profile.ko_screen_results:
            if not result.passed:
                return False, result.ko_id
        return True, None
