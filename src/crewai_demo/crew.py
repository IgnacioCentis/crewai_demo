from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from crewai_demo.tools.db_query_tool import DatabaseAnalyticsTool
from crewai_demo.tools.schema_tool import DatabaseSchemaTool


# =========================
# ROUTER CREW (classifier only)
# =========================
@CrewBase
class ChocolartRouter:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks_router.yaml"

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def router_analista(self) -> Agent:
        return Agent(
            config=self.agents_config["router_analista"],
            verbose=True,
            max_iter=2,
            allow_delegation=False,
        )

    @task
    def clasificar_consulta(self) -> Task:
        return Task(
            config=self.tasks_config["clasificar_consulta"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            cache=True,
        )


# =========================
# NO-DB CREW (respond without DB)
# =========================
@CrewBase
class ChocolartNoDb:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks_no_db.yaml"

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def router_analista(self) -> Agent:
        return Agent(
            config=self.agents_config["router_analista"],
            verbose=True,
            max_iter=2,
            allow_delegation=False,
        )

    @task
    def responder_sin_db(self) -> Task:
        return Task(
            config=self.tasks_config["responder_sin_db"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            cache=True,
        )


# =========================
# EXECUTOR CREW (DB)
# =========================
@CrewBase
class ChocolartAssistant:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks_assistant.yaml"

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def analista_datos(self) -> Agent:
        return Agent(
            config=self.agents_config["analista_datos"],
            verbose=True,
            max_iter=3,
            allow_delegation=False,
            tools=[DatabaseSchemaTool(), DatabaseAnalyticsTool()],
        )

    @task
    def responder_con_db(self) -> Task:
        return Task(
            config=self.tasks_config["responder_con_db"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            cache=True,
        )


# =========================
# INFORMES (igual que tenías)
# =========================
@CrewBase
class ChocolartInformes:
    tasks_config = "config/tasks_informes.yaml"

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def redactor_informes(self) -> Agent:
        return Agent(
            config=self.agents_config["redactor_informes"],
            verbose=True,
        )

    @task
    def generar_informe_conversacion(self) -> Task:
        return Task(
            config=self.tasks_config["generar_informe_conversacion"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )