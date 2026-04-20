#!/usr/bin/env python
import sys
import warnings

from crewai_demo.crew import ChocolartAssistant, ChocolartNoDb, ChocolartRouter

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")



def run():
    """
    Run the crew (Chocolart assistant con router + executor).
    """
    user_msg = "Hola Soy tu ChocoAnalista, ¿qué datos necesitas consultar?"

    inputs = {
        "session_id": "cli_session",
        "message": user_msg,
        "conversation_history": "[]",
    }

    try:
        # 1️ROUTER
        router = ChocolartRouter().crew()
        decision = router.kickoff(inputs=inputs)

        # 🔍 DEBUG (te recomiendo dejarlo)
        print("Decision:", decision)

        # 2️DECISIÓN
        if "DB_REQUIRED" in str(decision):
            executor = ChocolartAssistant().crew()
            result = executor.kickoff(inputs=inputs)
        else:
            no_db = ChocolartNoDb().crew()
            result = no_db.kickoff(inputs=inputs)

        print("Respuesta:", result)

    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "session_id": "cli_session",
        "message": "Ejemplo de entrenamiento",
        "conversation_history": "[]",
    }
    try:
        ChocolartAssistant().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        ChocolartAssistant().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "session_id": "cli_session",
        "message": "Test",
        "conversation_history": "[]",
    }

    try:
        ChocolartAssistant().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "session_id": "trigger_session",
        "message": str(trigger_payload),
        "conversation_history": "[]",
    }

    try:
        result = ChocolartAssistant().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
