from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from crewai_demo.tools.db_query_tool import DatabaseAnalyticsTool


@CrewBase
class ChocolartAssistant:
    """Crew de chat: un agente analista con herramienta de consulta a la DB."""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def analista_datos(self) -> Agent:
        return Agent(
            config=self.agents_config["analista_datos"],  # type: ignore[index]
            verbose=True,
            tools=[DatabaseAnalyticsTool()],
        )

    @task
    def responder_chat(self) -> Task:
        return Task(
            config=self.tasks_config["responder_chat"],  # type: ignore[index]
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )


@CrewBase
class ChocolartInformes:
    """Crew de informes: agente redactor que resume la conversación en Markdown."""

    tasks_config = "config/tasks_informes.yaml"

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def redactor_informes(self) -> Agent:
        return Agent(
            config=self.agents_config["redactor_informes"],  # type: ignore[index]
            verbose=True,
        )

    @task
    def generar_informe_conversacion(self) -> Task:
        return Task(
            config=self.tasks_config["generar_informe_conversacion"],  # type: ignore[index]
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
