# Contexto y Documentación Técnica: ISILeg Web (Senado Santa Fe)

**URL Oficial**: https://isilegweb.senadosantafe.gob.ar/  
**Bot de Telegram**: [@isileg_bot](https://t.me/isileg_bot) (Estado: Listo y configurado para despliegue en Render)  
**Última Actualización**: 2026-08-25  
**Conversation ID**: `e83ef439-f27f-4b62-bcdb-ef3b01dcdbab`

---

## 1. Resumen Ejecutivo

**ISILeg Web** es el portal oficial del Sistema de Información Legislativa de la Cámara de Senadores de la Provincia de Santa Fe. Centraliza la actividad parlamentaria, la producción normativa y el seguimiento de expedientes.

Técnicamente, se compone de:
1. Una aplicación web de una sola página (**SPA**) desarrollada en **Angular** (v14+ con Angular Material).
2. Un backend con una **API REST pública en `/api/`** que entrega datos estructurados en formato JSON.
3. Repositorio de documentos en formato **PDF** (textos sancionados, versiones actualizadas, fojas escaneadas de expedientes y diarios de sesiones).
4. **Bot de Telegram (`bot.py`)**: Asistente interactivo con botones inline para búsqueda de leyes, descarga de documentos oficiales y navegación por normas modificatorias y vinculadas.
5. **Servidor HTTP Embebido & Dockerfile**: Puerto 8080 para Health Checks de Render (Free Tier), permitiendo ejecución 24/7 en la nube sin depender de la PC encendida.

---

## 2. Métricas y Volumen de Datos (Actualizado al 25/08/2026)

| Entidad | Cantidad de Registros | Endpoint Principal |
| :--- | :--- | :--- |
| **Leyes Provinciales** | 13.465 | `GET /api/ley?tiposLey=1` |
| **Decretos Leyes** | 617 | `GET /api/ley?tiposLey=2` |
| **Decretos** | 2.095 | `GET /api/ley?tiposLey=3` |
| **Expedientes Parlamentarios** | 57.905 | `GET /api/expediente` |
| **Sesiones Legislativas** | 819 | `GET /api/sesion` |
| **Departamentos Provinciales** | 19 | `GET /api/nomencladores/departamento` |
| **Áreas / Reparticiones** | 65 | `GET /api/nomencladores/areas` |
| **Bloques Políticos** | 17 | `GET /api/nomencladores/bloques` |

---

## 3. Componentes Desarrollados

### 3.1. Cliente API (`isileg_api.py`)
Módulo asíncrono con soporte para:
- Búsqueda por número (`search_leyes(numero_ley=...)`).
- Búsqueda por tema/palabras clave (`search_leyes(palabras_clave=...)`).
- Ficha técnica completa de la ley (`get_ley_detail(id_ley)`).
- Descarga de archivos PDF (`get_pdf_bytes(...)`).
- Extracción y análisis de normas vinculadas (`extract_related_norms(detail)`).

### 3.2. Bot de Telegram (`bot.py`)
- Detección inteligente de número de ley vs búsqueda de texto libre.
- Tarjetas con estado de vigencia con formato visual y fechas oficiales.
- Botones interactivos (Inline Keyboard) para descarga de PDFs directo al chat.
- Desglose y navegación de leyes vinculadas/modificatorias.
- Paginación interactiva de resultados temáticos.

---

## 4. Catálogo de Endpoints REST

- Base URL: `https://isilegweb.senadosantafe.gob.ar/api/`
- Leyes: `GET /api/ley?tiposLey=1&pagNro=0&pagCant=10&orden=desc`
- Detalle: `GET /api/ley/{idLey}`
- PDFs de Leyes:
  - Original: `GET /api/ley/pdfFile/{idLey}/1`
  - Ficha Técnica: `GET /api/ley/pdfFicha/{idLey}`
- Expedientes: `GET /api/expediente` (Pases de comisiones en `/rc`, tratamiento en `/tt`, PDF original en `/pdfFile/proyecto-original/{id}`).
- Sesiones: `GET /api/sesion` (Asistencia en `/as`, Asuntos Entrados en `/ae`, Diario en `/pdfDiarioSesion/{id}`).
