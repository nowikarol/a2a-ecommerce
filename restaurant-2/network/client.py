import asyncio
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import nest_asyncio

nest_asyncio.apply()

URL_HURTOWNI = {
    "H1": "",
    "H2": ""
}

async def wywolaj_zdalne_narzedzie(url: str, nazwa_narzedzia: str, argumenty: dict) -> str:
    """Łączy się z serwerem hurtowni i wywołuje jej narzędzie."""
    try:
        async with sse_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                wynik = await session.call_tool(nazwa_narzedzia, arguments=argumenty)
                return wynik.content[0].text if wynik.content else "Brak odpowiedzi"
    except Exception as e:
        return f"Błąd sieciowy z {url}: {e}"