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

## ☁️ Despliegue 24/7 en Render (Gratis)

El proyecto incluye todos los archivos necesarios para ejecutarse en la nube sin depender de tu PC:
- `Dockerfile`: Contenedor liviano de Python 3.13 con certificados y dependencias.
- `render.yaml`: Blueprint para desplegar en Render como **Web Service (Plan Free)**.
- Servidor HTTP integrado en `bot.py` para Health Checks automáticos de Render en el puerto `8080`.

### 🚀 Pasos para Desplegar en Render:
1. Sube este proyecto a tu cuenta de **GitHub** (ej: `domingorondina/isileg-telegram-bot`).
2. Entra a tu cuenta en [dashboard.render.com](https://dashboard.render.com/).
3. Haz clic en **New +** ➡️ **Web Service** (o **Blueprint** conectando el repo).
4. Selecciona tu repositorio `isileg-telegram-bot`.
5. En la sección **Environment Variables**, agrega:
   - `TELEGRAM_BOT_TOKEN`: `tu_token_aqui`
   - `PORT`: `8080`
6. Haz clic en **Create Web Service**. ¡En 2 minutos estará activo 24/7 en la nube!

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
