---
title: "Cómo funciona Daily Journal"
description: "Un artículo técnico en profundidad cada día laborable, con temas propuestos por el equipo."
pubDate: 2026-06-10
tags: ["meta"]
---

Cada día laborable a primera hora se publica aquí un artículo técnico (~15 minutos de lectura) sobre un tema propuesto por el equipo: desde cero hasta los detalles que una newsletter generalista no cuenta, con ejemplos de código ejecutables.

## Proponer un tema

Abre una issue en el [repositorio](https://github.com/jlfernandezfernandez/daily-journal/issues/new?labels=topic) con el label `topic`. El cuerpo de la issue admite notas de enfoque ("no entendemos X, compáralo con Y"). El label `priority` salta la cola.

Cada noche, una GitHub Action coge el siguiente tema, genera el artículo con un LLM y cierra la issue con el link al resultado.

## La estructura de cada artículo

1. **Contexto**: qué problema existe y por qué el tema importa, desde cero.
2. **Concepto central**: la idea clave explicada con precisión.
3. **En profundidad**: internals, trade-offs y comparativas.
4. **Código**: ejemplos completos y ejecutables, de menos a más complejo.
5. **Trampas comunes**: errores reales y cómo evitarlos.
6. **Para saber más**: referencias concretas para seguir.
