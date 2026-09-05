"""
Cliente de Integración con ISILeg Web (Senado de Santa Fe)
Soporta consultas directas y puente de proxy ultra rápido a través de ScraperAPI (country_code=ar) para despliegues en la nube (Render).
"""

import os
import httpx
import re
import urllib.parse
from typing import Optional, Dict, Any, List

BASE_URL = "https://isilegweb.senadosantafe.gob.ar/api"
DEFAULT_TIMEOUT = 10.0

class ISILegAPI:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
            "Referer": "https://isilegweb.senadosantafe.gob.ar/",
            "Origin": "https://isilegweb.senadosantafe.gob.ar"
        }

    async def _fetch_json(self, raw_url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Realiza la petición HTTP GET de datos JSON a ISILeg Web.
        Intenta primero la conexión directa con un timeout rápido de 3.5s.
        Si la IP de la nube está bloqueada por el cortafuegos provincial, pasa de inmediato
        al fallback automático vía proxy CORS (proxy.cors.sh).
        """
        if params:
            query_str = urllib.parse.urlencode(params)
            sep = "&" if "?" in raw_url else "?"
            direct_url = f"{raw_url}{sep}{query_str}"
        else:
            direct_url = raw_url

        # Intento 1: Conexión directa
        async with httpx.AsyncClient(verify=False, timeout=3.5) as client:
            try:
                resp = await client.get(direct_url, headers=self.headers)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                pass

        # Intento 2: Fallback automático por proxy CORS para evitar geo-bloqueo de Render
        proxy_url = f"https://proxy.cors.sh/{direct_url}"
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            resp = await client.get(proxy_url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def _fetch_bytes(self, sub_path: str) -> Optional[bytes]:
        """
        Descarga el binario PDF desde ISILeg.
        """
        raw_url = f"{self.base_url}/{sub_path.lstrip('/')}"
        
        async with httpx.AsyncClient(verify=False, timeout=3.5) as client:
            try:
                resp = await client.get(raw_url, headers=self.headers)
                if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                    return resp.content
            except Exception:
                pass

        proxy_url = f"https://proxy.cors.sh/{raw_url}"
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            try:
                resp = await client.get(proxy_url, headers=self.headers)
                if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                    return resp.content
            except Exception:
                pass
        return None

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

        raw_url = f"{self.base_url}/ley"
        return await self._fetch_json(raw_url, params)

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
        if isinstance(res, dict) and "data" in res and isinstance(res["data"], dict):
            return res["data"]
        return res if isinstance(res, dict) else {}

    async def get_pdf_bytes(self, sub_path: str) -> Optional[bytes]:
        """
        Descarga el binario PDF desde ISILeg.
        """
        return await self._fetch_bytes(sub_path)

    def extract_related_norms(self, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extrae leyes modificatorias o vinculadas a partir de comentarios y nomencladores.
        """
        related = []
        comentario = detail.get("comentario") or ""
        
        # Regex para capturar referencias a leyes
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
