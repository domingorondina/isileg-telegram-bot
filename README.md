# ISILeg Web & Bot de Telegram - Cámara de Senadores de Santa Fe

Repositorio de análisis, herramientas e integración con la plataforma **ISILeg Web** de la Cámara de Senadores de la Legislatura de la Provincia de Santa Fe (Argentina).

Sitio Oficial: [https://isilegweb.senadosantafe.gob.ar/](https://isilegweb.senadosantafe.gob.ar/)

---

## 🤖 Bot de Telegram

Un bot interactivo para Telegram que permite consultar y descargar leyes provinciales directamente:
- 🔢 **Búsqueda por Número de Ley**: Escribe directamente el número (ej: `12510` o `14477`) y obtén la ficha de la norma.
- 🔎 **Búsqueda Temática**: Escribe palabras clave (ej: `salud`, `presupuesto`, `seguridad vial`) para ver resultados con paginación interactiva.
- 📄 **Descargas con un Clic**:
  - PDF del texto original.
  - PDF del texto actualizado.
  - Ficha técnica en PDF.
- 🔗 **Exploración de Normas Vinculadas**: Detecta automáticamente leyes modificatorias y decretos vinculados para consultarlos con botones interactivos.

---

## ☁️ Despliegue en la Nube (Render 24/7)

El bot se encuentra desplegado y funcionando de manera continua en la nube:
- **Bot de Telegram**: [@isileg_bot](https://t.me/isileg_bot)
- **Repositorio GitHub**: [https://github.com/domingorondina/isileg-telegram-bot](https://github.com/domingorondina/isileg-telegram-bot)
- **Dashboard Render**: [https://dashboard.render.com/web/srv-da6r8sh0er6s73d699pg](https://dashboard.render.com/web/srv-da6r8sh0er6s73d699pg)
- **Health Check URL**: [https://isileg-telegram-bot.onrender.com](https://isileg-telegram-bot.onrender.com)
- **Estado**: 🟢 **LIVE (24/7 Activo sin necesidad de PC encendida)**

---

### 💻 Ejecución Local Opcional

Si deseas ejecutarlo localmente en tu computadora:
1. Haz doble clic en [`run_bot.bat`](file:///g:/Mi%20unidad/antigravity/isileg/run_bot.bat) o ejecuta:
   ```bash
   python bot.py
   ```

---

## 📂 Contenido del Proyecto

- `bot.py`: Lógica del Bot de Telegram (Handlers, teclados Inline, envío de documentos).
- `isileg_api.py`: Cliente asíncrono en Python para consumir la API REST de ISILeg y descargar PDFs.
- `requirements.txt`: Dependencias del proyecto (`python-telegram-bot`, `httpx`, `python-dotenv`).
- `.env`: Archivo de configuración para el token del bot.
- `test_isileg_api.py`: Test unitario de integración con la API de ISILeg.
- `CONTEXTO.md`: Documentación técnica de arquitectura, endpoints y volumen de datos.
