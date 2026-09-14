import uuid
from dotenv import load_dotenv
from data.database import init_db
from agent.agent import setup_agent

def chat_loop(agent):
    aktualny_watek = str(uuid.uuid4())
    config = {"configurable": {"thread_id": aktualny_watek}}
    
    print("=" * 50)
    print("🧠 SYSTEM ZAOPATRZENIA (AGENT) URUCHOMIONY")
    print("Agent jest gotowy na Twoje polecenia.")
    print("Wpisz 'reset', aby wyczyścić pamięć Agenta i rozpocząć nowe zadanie.")
    print("Wpisz 'wyjscie', aby zamknąć program.")
    print("=" * 50)

    while True:
        polecenie = input("\nSZEF: ")
        
        if polecenie.strip().lower() in ['koniec', 'wyjscie', 'exit', 'quit']:
            print("AGENT: Do widzenia, Szefie! Czat wyłączony (Serwer działa dalej w tle, jeśli go uruchomiłeś).")
            break
            
        if polecenie.strip().lower() == 'reset':
            aktualny_watek = str(uuid.uuid4())
            config = {"configurable": {"thread_id": aktualny_watek}}
            print(f"🔄 [SYSTEM]: Pamięć wyczyszczona. Otwarto nowy wątek ({aktualny_watek}).")
            continue
            
        if not polecenie.strip():
            continue

        print("AGENT: (Myślę...)")
        wynik = agent.invoke({"messages": [("user", polecenie)]}, config)
        
        odpowiedz_agenta = wynik["messages"][-1].content
        print(f"\nAGENT:\n{odpowiedz_agenta}")
        print("-" * 50)

if __name__ == "__main__":
    # 1. Ładujemy klucze
    load_dotenv()

    # 2. Inicjalizacja bazy (nic nie popsuje, jeśli baza już jest!)
    init_db()

    # 3. Uruchamiamy samego Agenta
    my_agent = setup_agent()
    chat_loop(my_agent)