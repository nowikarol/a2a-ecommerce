import asyncio
import os
from dotenv import load_dotenv
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv() # Wczytuje zmienne środowiskowe z pliku .env do pamięci programu

URL_HURTOWNI = {
    "H1": os.getenv("H1_MCP_URL", "http://127.0.0.1:8001/sse"),
    "H2": os.getenv("H2_MCP_URL", "http://127.0.0.1:8002/sse")
}

async def dopasuj_narzedzie_llm(dostepne_narzedzia: list, intencja: str) -> str:
    """
    Wybiera odpowiednie narzędzie z listy udostępnianej przez serwer MCP
    na podstawie jego nazwy i opisu, jeśli standardowa nazwa jest niedostępna.
    """
    if not dostepne_narzedzia: # Jeśli serwer nie wystawił żadnych narzędzi, od razu przerywamy
        return None
        
    opisy = [f"- {t.name}: {t.description}" for t in dostepne_narzedzia] # Tworzymy czytelną dla modelu językowego listę narzędzi (nazwa: opis)
    opisy_str = "\n".join(opisy)
    
    prompt = (
        f"Zadanie do wykonania: {intencja}\n\n"
        f"Dostępne narzędzia na zdalnym serwerze:\n{opisy_str}\n\n"
        f"Wybierz JEDNO narzędzie, które najlepiej pasuje do zadania. "
        f"Zwróć TYLKO jego dokładną nazwę (bez cudzysłowów i dodatkowych słów). "
        f"Jeśli żadne narzędzie nie pasuje, zwróć słowo NONE."
    )
    
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.0)
        # Wysyłamy zapytanie do modelu jako zadanie asynchroniczne (ainvoke)
        odpowiedz = await llm.ainvoke([
            SystemMessage(content="Jesteś precyzyjnym routerem narzędzi. Zwracasz wyłącznie samą nazwę wybranego narzędzia."),
            HumanMessage(content=prompt)
        ])
        
        wybor = odpowiedz.content.strip().strip("'\"` \n\t") # Oczyszczamy odpowiedź z niepotrzebnych znaków i białych spacji

        # Upewniamy się, że narzędzie wybrane przez LLM faktycznie znajduje się na liście serwera
        for t in dostepne_narzedzia:
            if t.name.lower() == wybor.lower():
                return t.name
                
    except Exception as e:
        print(f"[LLM ROUTER] Błąd działania modelu dopasowującego: {e}")
        
    return None

async def wywolaj_zdalne_narzedzie(url: str, domyslna_nazwa: str, intencja: str, argumenty: dict) -> str:
    """Główna funkcja sieciowa. Łączy się z serwerem hurtowni, szuka właściwego narzędzia i wywołuje je.
    """
    try:
        # Nawiązanie asynchronicznego połączenia Server-Sent Events (SSE)
        async with sse_client(url) as streams:
            # Ustanowienie sesji protokołu MCP
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                
                # Pobranie listy wszystkich narzędzi udostępnianych przez serwer
                lista_narzedzi = await session.list_tools()
                nazwy_narzedzi = [t.name for t in lista_narzedzi.tools]
                
                wybrane_narzedzie = None
                
                # Sprawdzamy, czy serwer wystawia narzędzie pod taką samą nazwą, jakiej oczekujemy
                if domyslna_nazwa in nazwy_narzedzi:
                    wybrane_narzedzie = domyslna_nazwa
                else:
                    # Narzędzia nie ma. Zlecamy analizę modelowi 
                    wybrane_narzedzie = await dopasuj_narzedzie_llm(lista_narzedzi.tools, intencja)
                
                # Jeśli po analizie nadal nie ma odpowiedniego narzędzia, rzucamy błąd
                if not wybrane_narzedzie:
                    return f"Błąd: Serwer ({url}) nie posiada narzędzia wspierającego operację: {intencja}"
                
                wynik = await session.call_tool(wybrane_narzedzie, arguments=argumenty) # Faktyczne wykonanie operacji na zdalnym serwerze
                return wynik.content[0].text if wynik.content else "Brak odpowiedzi" # Zwracamy odpowiedź serwera, jeśli jest dostępna
    except Exception as e:
        return f"Błąd sieciowy z {url}: {e}"