"""
Cliente de Integración con ISILeg Web (Senado de Santa Fe)
Soporta consultas directas (entorno local en Argentina) y puente de proxy automático a través de ScraperAPI (country_code=ar) para despliegues en la nube (Render).
"""

import os
import httpx
import re
import logging
import urllib.parse
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

BASE_URL = "https://isilegweb.senadosantafe.gob.ar/api"
DEFAULT_TIMEOUT = 15.0

class ISILegAPI:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

    async def _fetch_json(self, raw_url: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """
        Obtiene JSON de ISILeg. Intenta conexión directa (rápida si se ejecuta en Argentina)
        y ante cualquier falla o timeout (como en Render en EE.UU.), conmuta automáticamente
        a ScraperAPI con geolocalización en Argentina (country_code=ar).
        """
        # 1. Intento directo (timeout corto 2.5s)
        try:
            async with httpx.AsyncClient(verify=False, timeout=2.5) as client:
                resp = await client.get(raw_url, headers=self.headers)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.debug(f"Direct ISILeg fetch failed/timed out, switching to ScraperAPI AR: {e}")

        # 2. Conmutación a ScraperAPI (country_code=ar) para la nube
        scraper_key = os.getenv("SCRAPER_API_KEY", "4b0fab5f99b2d71c635ab26eacdac192")
        proxy_url = f"http://api.scraperapi.com?api_key={scraper_key}&country_code=ar&url={urllib.parse.quote(raw_url)}"
        
        async with httpx.AsyncClient(verify=False, timeout=timeout) as client:
            resp = await client.get(proxy_url)
            resp.raise_for_status()
            return resp.json()

    async def search_leyes(
        self,
        numero_ley: Optional[str] = None,
        palabras_clave: Optional[str] = None,
        asunto: Optional[str] = None,
        tipo_ley: int = 1, # 1: Ley, 2: Decreto Ley, 3: Decreto
        page: int = 0,
        page_size: int = 5,
        orden: str = "desc"
    ) -> Dict[str, Any]:
        """
        Busca leyes en ISILeg según número o palabras clave.
        """
        params = {
            "tiposLey": str(tipo_ley),
            "pagNro": str(page),
            "pagCant": str(page_size),
            "orden": orden
        }
        
        if numero_ley:
            clean_num = "".join(filter(str.isdigit, str(numero_ley)))
            if clean_num:
                params["numeroLey"] = clean_num
                
        if palabras_clave:
            params["palabrasClave"] = palabras_clave
            
        if asunto:
            params["asunto"] = asunto

        raw_url = f"{self.base_url}/ley?{urllib.parse.urlencode(params)}"
        return await self._fetch_json(raw_url)

    async def get_ley_by_number(self, numero_ley: str, tipo_ley: int = 1) -> Optional[Dict[str, Any]]:
        """
        Busca directamente una ley por su número exacto y devuelve el primer resultado.
        """
        data = await self.search_leyes(numero_ley=numero_ley, tipo_ley=tipo_ley, page=0, page_size=1)
        items = data.get("data", [])
        if items and len(items) > 0:
            return items[0]
        return None

    async def get_ley_detail(self, id_ley: int) -> Dict[str, Any]:
        """
        Obtiene el detalle completo de una norma mediante su ID.
        """
        raw_url = f"{self.base_url}/ley/{id_ley}"
        res = await self._fetch_json(raw_url)
        return res.get("data", {})

    async def get_pdf_bytes(self, pdf_path: str) -> Optional[bytes]:
        """
        Descarga el stream binario de un PDF dado su sub-path (ej. 'ley/pdfFile/6684/1').
        """
        clean_path = pdf_path.lstrip('/')
        raw_url = f"{self.base_url}/{clean_path}"

        # 1. Intento directo
        try:
            async with httpx.AsyncClient(verify=False, timeout=3.0) as client:
                resp = await client.get(raw_url, headers=self.headers)
                if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                    return resp.content
        except Exception:
            pass

        # 2. ScraperAPI fallback para la nube
        scraper_key = os.getenv("SCRAPER_API_KEY", "4b0fab5f99b2d71c635ab26eacdac192")
        proxy_url = f"http://api.scraperapi.com?api_key={scraper_key}&country_code=ar&url={urllib.parse.quote(raw_url)}"
        try:
            async with httpx.AsyncClient(verify=False, timeout=20.0) as client:
                resp = await client.get(proxy_url)
                if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                    return resp.content
        except Exception:
            pass

        return None

    def extract_related_norms(self, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extrae leyes modificatorias o vinculadas a partir de comentarios y nomencladores.
        """
        related = []
        comentario = detail.get("comentario") or ""
        
        matches = re.finditer(r"(?:Ley|Decreto Ley|Decreto|D\.L\.)\s*(?:N[°ºo\.]*)?\s*(\d+)", comentario, re.IGNORECASE)
        seen = set()
        for m in matches:
            num = m.group(1)
            if num not in seen and num != str(detail.get("numeroLey")):
                seen.add(num)
                tipo = "Ley"
                match_str = m.group(0).lower()
                if "decreto ley" in match_str or "d.l." in match_str:
                    tipo = "Decreto Ley"
                elif "decreto" in match_str:
                    tipo = "Decreto"

                start = max(0, m.start() - 30)
                end = min(len(comentario), m.end() + 50)
                snippet = comentario[start:end].replace("\r", " ").replace("\n", " ").strip()

                related.append({
                    "tipo": tipo,
                    "numero": num,
                    "contexto": f"...{snippet}..."
                })

        return related
