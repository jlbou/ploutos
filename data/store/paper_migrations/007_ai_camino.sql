-- Con QUE se tomo cada decision del analista (24/09/2026, antes de desplegar la fase 3).
--
-- El protocolo de la fase 6 (docs/archivo/protocolo-fase-6.md, decision 1 del propietario) cuenta la
-- muestra desde el despliegue de la fase 3 y la PARTE en tramos si cambia el camino de
-- decision: prompt, contrato, modelo, estrategia, riesgo o comisiones. Sin estas dos
-- columnas, el journal no dejaba saber que decisiones se tomaron con que version, y
-- un cambio a mitad mezclaria dos IAs distintas en la misma cuenta sin que nadie lo viera.
--
-- `camino`: huella (12 hex) de todo lo que define la decision (ver ai.journal.camino).
-- `modelo`: el modelo que respondio DE VERDAD, si el CLI lo dice (`modelUsage`); el
--           `model: sonnet` de la configuracion es un alias y puede cambiar por debajo.

ALTER TABLE ai_calls ADD COLUMN camino TEXT;
ALTER TABLE ai_calls ADD COLUMN modelo TEXT;
