# Reporte de Evaluación de Candidatos
## Cliente: Clínica Salud Valencia S.L.

> **Generado por:** NovaHiring Evaluation Engine  
> **Fecha:** 20 de mayo de 2026  
> **Contacto cliente:** Marcos Ferrer — Director de Operaciones  
> **Posición:** Desarrollador/a Full Stack — Sistema de gestión de citas  
> **Candidatos evaluados:** 6  
> **Método:** CV Screening contra perfil generado en discovery  
> **Decisión final:** Humano

---

## Resumen Ejecutivo

De los 6 candidatos evaluados, **3 fueron descartados** por no superar los criterios de eliminación directa (knockout) del perfil. Los **3 candidatos aptos** demuestran las competencias técnicas y blandas requeridas. La recomendación de entrevista presencial está ordenada por relevancia al caso concreto del cliente.

---

## Criterios de Descarte (Knockouts)

Estos criterios se evalúan antes del scoring. Si alguno falla, el candidato es descartado independientemente de su puntaje en otras dimensiones.

| ID | Criterio | Razón |
|----|----------|-------|
| KO1 | Sin experiencia con WhatsApp Business API (Meta) | Única herramienta de notificaciones que el cliente acepta |
| KO2 | Sin comprensión de RGPD/LOPDGDD para datos sanitarios | Datos de salud son categoría especial; riesgo legal inaceptable |
| KO3 | Solo puede trabajar con supervisión técnica externa | La clínica no tiene perfil técnico interno |

---

## Scorecard — Dimensiones y Pesos

| ID | Dimensión | Peso |
|----|-----------|------|
| D1 | Integraciones técnicas (WhatsApp, Calendar, Panel, Reservas) | 3 |
| D2 | RGPD/LOPDGDD datos sanitarios | 3 |
| D3 | Autonomía y toma de decisiones técnicas | 3 |
| D4 | Pragmatismo — construir vs usar herramientas | 3 |
| D5 | Entrega en plazos ajustados | 2 |
| D6 | Comunicación con perfiles no técnicos | 2 |
| D7 | Experiencia en sector salud | 2 |
| D8 | Stack e infraestructura adecuada al presupuesto | 1 |
| | **Total peso** | **19** |

**Fórmula:** `Score final = Σ(score × peso) / 19` · Escala 1–5 por dimensión

---

## Candidatos Descartados

### ❌ Miguel Torres Sánchez — TRIPLE DESCARTE (KO1 + KO2 + KO3)

**Motivo:**
El candidato falla los tres criterios de eliminación simultáneamente. Su CV describe un perfil de desarrollador en equipo organizado con supervisión técnica: "Consumí APIs de terceros siguiendo documentación técnica facilitada por el equipo de arquitectura" y "me gusta trabajar en entornos organizados con roles bien definidos". No tiene experiencia con WhatsApp Business API, no menciona RGPD/LOPDGDD y su forma de trabajo es incompatible con la autonomía total que requiere la clínica.

**Perfil adecuado para:** Empresa de producto con equipo de ingeniería estructurado, roles definidos y arquitecto que guíe las decisiones técnicas.

---

### ❌ Ana Patricia Lombard Vidal — TRIPLE DESCARTE (KO1 + KO2 + KO3)

**Motivo:**
Stack enterprise incompatible (Angular + Java Spring Boot + Oracle DB) con el contexto y presupuesto del cliente. Sin experiencia en WhatsApp Business API, sin conocimiento de RGPD para datos sanitarios, y siempre ha trabajado en estructuras corporativas con arquitecto técnico y líder de proyecto. Su experiencia freelance fue "coordinada con la agencia que gestionaba al cliente final" — nunca tuvo contacto directo con el cliente no técnico.

**Perfil adecuado para:** Corporaciones del sector financiero o energético con equipos estructurados, dashboards complejos y sistemas enterprise.

---

### ❌ Jhordan Andrés Asprilla Solis — DESCARTE (KO2)

**Motivo:**
El candidato supera KO1 (tiene experiencia con WhatsApp Business API de Meta) pero no supera KO2. Su CV no menciona RGPD, LOPDGDD, protección de datos sanitarios ni cumplimiento legal en ninguno de sus proyectos. Toda su experiencia es en fintech, chatbots de IA e inventarios — ninguno implica datos de salud de categoría especial. Para una clínica con obligaciones estrictas de LOPDGDD, el riesgo legal es inaceptable.

**Nota:** Tiene potencial técnico (WhatsApp API, FastAPI, microservicios, cloud). Candidato a reconsiderar en proyectos sin datos sanitarios. Si hubiera una instancia de verificación, valdría la pena confirmar si tiene conocimiento RGPD no documentado en el CV.

---

## Candidatos Aptos — Ranking

### 🥇 #1 — Sofía Delgado Herrera

| Dimensión | Peso | Score | Puntos |
|-----------|------|-------|--------|
| D1 — Integraciones técnicas | 3 | 5 | 15 |
| D2 — RGPD/LOPDGDD sanitario | 3 | 5 | 15 |
| D3 — Autonomía técnica | 3 | 5 | 15 |
| D4 — Pragmatismo build vs buy | 3 | 4 | 12 |
| D5 — Entrega en plazos | 2 | 5 | 10 |
| D6 — Comunicación no técnicos | 2 | 5 | 10 |
| D7 — Sector salud | 2 | 5 | 10 |
| D8 — Stack e infraestructura | 1 | 5 | 5 |
| **TOTAL** | **19** | — | **92/95** |

**Score final: 4.84 / 5.00 (96.8%)**

**Por qué es la #1:**

Sofía Delgado es el perfil de mayor alineación con el caso de la Clínica Salud Valencia. El punto de diferenciación más contundente es **SaludConnect**: entregó un sistema completo de gestión de citas para 4 clínicas privadas en Cataluña en **11 semanas, por debajo del plazo de 3 meses acordado** — exactamente el plazo y el tipo de proyecto que el cliente necesita. Es el único candidato con entrega documentada en el mismo plazo que Marcos Ferrer exige.

Sus otras ventajas sobre el resto:

La implementación de RGPD es la más completa del grupo: además del RAT (que tienen Carlos y Elena), elaboró el **AIPD (Análisis de Impacto de Protección de Datos)**, que es el documento más avanzado de cumplimiento para datos de categoría especial. Tiene formación específica en datos sanitarios (AEPD + SEDIA), no solo DPO genérico.

En la comunicación con el cliente, su CV menciona **reuniones quincenales con la dirección y con Lucía**, la recepcionista, para validar funcionalidades y recoger feedback. Es la coincidencia más directa con la situación real de Marcos Ferrer: el director de operaciones y la recepcionista son exactamente los interlocutores que tendría en Valencia.

En infraestructura, usa GCP Cloud Run (serverless, pago por uso), que es la opción más económica del grupo para el volumen de la clínica y escala automáticamente si la apertura de fisioterapia dobla los pacientes.

Lleva 8 años construyendo sistemas exclusivamente en salud y bienestar (clínicas, psicólogos, fisioterapeutas, nutricionistas). No solo conoce la tecnología; conoce el dominio.

**Preguntas clave para la entrevista:**
- ¿Qué construiste desde cero en SaludConnect y qué usaste de herramientas existentes? ¿Cuál fue el criterio?
- Con 8.000-12.000€ y 3 meses, ¿qué garantizarías para junio y qué dejarías en la hoja de ruta?
- ¿Cómo manejarías al médico que sigue con agenda de papel?

---

### 🥈 #2 — Carlos Andrés Rivas Mendoza

| Dimensión | Peso | Score | Puntos |
|-----------|------|-------|--------|
| D1 — Integraciones técnicas | 3 | 5 | 15 |
| D2 — RGPD/LOPDGDD sanitario | 3 | 4 | 12 |
| D3 — Autonomía técnica | 3 | 5 | 15 |
| D4 — Pragmatismo build vs buy | 3 | 5 | 15 |
| D5 — Entrega en plazos | 2 | 5 | 10 |
| D6 — Comunicación no técnicos | 2 | 5 | 10 |
| D7 — Sector salud | 2 | 4 | 8 |
| D8 — Stack e infraestructura | 1 | 5 | 5 |
| **TOTAL** | **19** | — | **90/95** |

**Score final: 4.74 / 5.00 (94.7%)**

**Por qué es el #2:**

Carlos fundó y operó **CitaFácil**, un SaaS de reservas médicas para centros de salud en España con **12 clínicas activas**. Es el único candidato que no solo construyó un sistema similar, sino que lo llevó a producción como producto, gestionó la relación comercial y técnica con los clientes, y realizó el onboarding presencial para explicar el sistema a personal no técnico. Eso es exactamente lo que necesita Marcos Ferrer.

Su punto más fuerte es el criterio de **entrega en plazos**: "MVPs funcionales en 6 a 12 semanas", con el lanzamiento de Reservalia en 10 semanas con 2 semanas de margen. Es el candidato más explícito sobre su velocidad de entrega.

Tiene el criterio **build vs buy** más evidente del grupo: usó DigitalOcean (más económico que AWS) en lugar de infraestructura propia, adoptó WhatsApp API oficial con plantillas aprobadas por Meta en lugar de soluciones custom. Con un presupuesto de 8.000-12.000€, este pragmatismo es crítico.

La única diferencia con Sofía es la profundidad del cumplimiento RGPD (sin AIPD) y que CitaFácil cerró en marzo de 2026 — lo que merece exploración en la entrevista.

**Preguntas clave para la entrevista:**
- CitaFácil cerró en 2026. ¿Qué pasó con los 12 clientes? ¿Cómo se gestionó la transición?
- Con 8.000-12.000€ y 3 meses, ¿qué MVP mínimo entregarías y qué dejarías fuera?
- ¿Cómo harías la migración desde Doctoralia al nuevo sistema garantizando continuidad?

---

### 🥉 #3 — Elena Martínez García

| Dimensión | Peso | Score | Puntos |
|-----------|------|-------|--------|
| D1 — Integraciones técnicas | 3 | 5 | 15 |
| D2 — RGPD/LOPDGDD sanitario | 3 | 5 | 15 |
| D3 — Autonomía técnica | 3 | 5 | 15 |
| D4 — Pragmatismo build vs buy | 3 | 4 | 12 |
| D5 — Entrega en plazos | 2 | 3 | 6 |
| D6 — Comunicación no técnicos | 2 | 5 | 10 |
| D7 — Sector salud | 2 | 5 | 10 |
| D8 — Stack e infraestructura | 1 | 4 | 4 |
| **TOTAL** | **19** | — | **87/95** |

**Score final: 4.58 / 5.00 (91.6%)**

**Por qué es la #3:**

Elena es una candidata muy sólida. MedAgenda Pro — su SaaS de gestión de citas para 15 consultorios en España con 99,8% de uptime durante 18 meses — es evidencia de un sistema maduro y confiable en producción. Tiene la **certificación DPO nivel básico** (AEPD Academy), que es el único título formal de protección de datos del grupo.

Su diferenciación frente a Sofía y Carlos es su **fiabilidad demostrada en producción** (18 meses, 99,8% uptime, 15 consultorios) y su certificación DPO. Para un cliente que teme que "algo falle y no saber por qué", Elena aporta la mayor garantía de estabilidad.

El único punto débil en su CV es la ausencia de **evidencia de entrega bajo presión de plazos ajustados** — no menciona cuánto tardó en construir MedAgenda Pro ni situaciones de deadline fijo. Para el plazo de junio de la clínica, esto genera incertidumbre que debe resolverse en la entrevista.

**Preguntas clave para la entrevista:**
- ¿Cuánto tiempo tardaste en construir el primer consultor funcional de MedAgenda Pro? ¿Has entregado algo en 3 meses o menos?
- Con un presupuesto de 8.000-12.000€, ¿usarías AWS (tu stack habitual) o migrarías a una alternativa más económica?
- ¿Cómo gestionarías una petición de nuevas funcionalidades cuando ya llevas 6 semanas trabajando y el deadline no se mueve?

---

## Tabla Comparativa Final

| # | Candidato | KO | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | Score | Estado |
|---|-----------|----|----|----|----|----|----|----|----|----|---------|----|
| 1 | Sofía Delgado | ✅ | 5 | 5 | 5 | 4 | 5 | 5 | 5 | 5 | **4.84** | APTA |
| 2 | Carlos Rivas | ✅ | 5 | 4 | 5 | 5 | 5 | 5 | 4 | 5 | **4.74** | APTO |
| 3 | Elena Martínez | ✅ | 5 | 5 | 5 | 4 | 3 | 5 | 5 | 4 | **4.58** | APTA |
| — | Jhordan Solis | ❌ KO2 | 3 | 1 | 3 | 4 | 3 | 2 | 1 | 4 | 2.84* | DESCARTADO |
| — | Miguel Torres | ❌ KO1+2+3 | — | — | — | — | — | — | — | — | — | DESCARTADO |
| — | Ana Lombard | ❌ KO1+2+3 | — | — | — | — | — | — | — | — | — | DESCARTADO |

*Score hipotético de Jhordan, no relevante para la decisión.

---

## Recomendación al Cliente

**Los tres candidatos aptos son válidos para la entrevista presencial en Valencia.** La diferencia entre ellos es de matices, no de capacidad técnica fundamental.

Si tuviéramos que priorizar una entrevista basándonos únicamente en el CV:

**Sofía Delgado primero**, por la coincidencia más directa con el proyecto: misma duración (3 meses), misma tipología (clínica privada), entrega adelantada documentada, y la referencia explícita a la recepcionista como stakeholder del sistema.

**Carlos Rivas segundo**, por su historial como fundador de un producto similar ya en producción con clientes reales, y por ser el más explícito en velocidad de entrega y pragmatismo de herramientas.

**Elena Martínez tercera**, por aportar la mayor fiabilidad en producción (99,8% uptime, 18 meses, 15 consultorios) y la única certificación formal en protección de datos del grupo.

**La decisión final, como siempre, es del reclutador y del cliente.** Este reporte provee la información estructurada para apoyar esa decisión; no la reemplaza.

---

## Trazabilidad

| Archivo | Descripción |
|---------|-------------|
| `data/discovery-clinica-salud-valencia.json` | Discovery estructurado del cliente con perfil y scorecard |
| `data/evaluations/eval-11-elena-martinez.json` | Evaluación completa de Elena Martínez |
| `data/evaluations/eval-12-carlos-rivas.json` | Evaluación completa de Carlos Rivas |
| `data/evaluations/eval-13-sofia-delgado.json` | Evaluación completa de Sofía Delgado |
| `data/evaluations/eval-10-jhordan-solis.json` | Evaluación y descarte de Jhordan Solis |
| `data/evaluations/eval-14-miguel-torres.json` | Evaluación y descarte de Miguel Torres |
| `data/evaluations/eval-15-ana-lombard.json` | Evaluación y descarte de Ana Lombard |

---

*NovaHiring — Reporte generado automáticamente. La decisión final siempre la toma el humano.*
