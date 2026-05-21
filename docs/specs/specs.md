#  Chatbot que realice una entrevista para un rol de Senior Full-Stack Developer

1. Definición del rol (Job Definition)

Título exacto y nivel (Senior, Staff, Lead?)
Áreas de responsabilidad (frontend, backend, arquitectura, liderazgo técnico?)
Si el rol es individual contributor o tiene gestión de personas
Salario / rango de compensación (para filtrar expectativas desde el inicio)

2. Reglas de negocio del proceso de selección

¿Cuántas etapas tiene el proceso? (screening → técnica → cultural → oferta)
¿Qué pasa si el candidato falla una pregunta crítica? ¿Se descarta automáticamente?
¿El chatbot decide o solo recopila y un humano revisa después?
¿Hay un puntaje mínimo para pasar a la siguiente fase?
¿Tiempo máximo de entrevista? (15 min, 30 min?)
¿Se puede retomar una entrevista pausada?
¿Qué idiomas soporta? (español, inglés, ambos?)


3. El stack técnico a evaluar
Necesitas definir exactamente qué tecnologías son obligatorias vs deseables. Por ejemplo:

Frontend: React, Vue, Angular?
Backend: Node, Python, Java, Go?
Base de datos: PostgreSQL, MongoDB, Redis?
Cloud: AWS, GCP, Azure?
DevOps: Docker, Kubernetes, CI/CD?
Prácticas: TDD, clean architecture, DDD?


4. Estructura de la entrevista

¿Qué categorías de preguntas? (técnicas, de comportamiento, situacionales, de sistema design)
¿Cuántas preguntas por categoría?
¿Las preguntas son fijas o dinámicas según las respuestas anteriores?
¿Hay preguntas de seguimiento si la respuesta es vaga?


5. El proyecto o contexto de trabajo
Esto es clave porque cambia completamente las preguntas. No es lo mismo evaluar para:

Una startup que construye desde cero (valoran autonomía, versatilidad, velocidad)
Una empresa con deuda técnica que necesita modernización (valoran refactoring, migraciones, pragmatismo)
Una empresa con producto maduro y escala (valoran performance, observabilidad, procesos)



6. Criterios de evaluación (scorecard)

¿Cómo se mide cada respuesta? ¿Rúbrica del 1 al 5?
¿Quién define qué es una "buena" respuesta?
¿Hay respuestas correctas o solo señales de madurez técnica?



7. Lo que también deberías definir (y mucha gente olvida)

Tono del chatbot: ¿formal, conversacional, técnico directo?
Manejo de respuestas evasivas: ¿el bot presiona o acepta y sigue?
Privacidad y datos: ¿dónde se guardan las respuestas? ¿GDPR/LFPDPPP?
Accesibilidad: ¿solo texto o también voz?
Integración: ¿el chatbot vive solo o se conecta a un ATS como Greenhouse, Lever, Workday?


## Stack y tipo de proyecto