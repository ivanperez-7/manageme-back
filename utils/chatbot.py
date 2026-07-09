import os
from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_community.utilities import SQLDatabase
from langchain_core.tools import ToolException
from sqlalchemy import create_engine, MetaData

TABLAS_PERMITIDAS = {
    'movimiento_movimiento',
    'movimiento_movimientoitem',
    'movimiento_detalleentrada',
    'movimiento_detallesalida',
    'productos_producto',
    'productos_categor\u00eda',
    'productos_equipo',
    'productos_lote',
    'productos_marca',
    'productos_proveedor',
    'productos_unidad',
    'organizacion_cliente',
    'organizacion_equipocliente',
    'organizacion_sucursal',
}

PII_COLUMNAS = frozenset({
    'rfc', 'telefono', 'email', 'direccion',
})

class _RestrictedQuerySQLDataBaseTool(QuerySQLDataBaseTool):
    def _run(self, query: str, run_manager=None):
        trimmed = query.strip()
        if not trimmed:
            raise ToolException("Query vacía.")
        first_word = trimmed.split(maxsplit=1)[0].upper() if trimmed.split() else ""
        if first_word not in ("SELECT", "WITH", "EXPLAIN"):
            raise ToolException(
                "Solo se permiten consultas SELECT, WITH y EXPLAIN. "
                "No puedes modificar datos (INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE, etc.)."
            )
        return super()._run(query, run_manager)


class _RestrictedSQLDatabaseToolkit(SQLDatabaseToolkit):
    def get_tools(self):
        tools = super().get_tools()
        for i, tool in enumerate(tools):
            if isinstance(tool, QuerySQLDataBaseTool):
                tools[i] = _RestrictedQuerySQLDataBaseTool(db=self._db)
        return tools


def _build_branch_rules(branch_id):
    return (
        f"REGLAS DE FILTRADO POR SUCURSAL (obligatorias):\n"
        f"Solo puedes ver datos de la sucursal con id={branch_id}.\n"
        f"Todas tus consultas deben filtrar por esta sucursal.\n"
        f"\n"
        f"Reglas por tabla:\n"
        f"- movimiento_movimiento:        WHERE sucursal_id = {branch_id}\n"
        f"- organizacion_cliente:         WHERE sucursal_id = {branch_id}\n"
        f"- productos_lote:               WHERE sucursal_id = {branch_id}\n"
        f"- movimiento_movimientoitem:    JOIN movimiento_movimiento\n"
        f"                                ON movimiento_movimientoitem.movimiento_id = movimiento_movimiento.id\n"
        f"                                WHERE movimiento_movimiento.sucursal_id = {branch_id}\n"
        f"- movimiento_detallesalida:     JOIN movimiento_movimiento\n"
        f"                                ON movimiento_detallesalida.movimiento_id = movimiento_movimiento.id\n"
        f"                                WHERE movimiento_movimiento.sucursal_id = {branch_id}\n"
        f"- movimiento_detalleentrada:    JOIN movimiento_movimiento\n"
        f"                                ON movimiento_detalleentrada.movimiento_id = movimiento_movimiento.id\n"
        f"                                WHERE movimiento_movimiento.sucursal_id = {branch_id}\n"
        f"- productos_unidad:             JOIN productos_lote\n"
        f"                                ON productos_unidad.lote_id = productos_lote.id\n"
        f"                                WHERE productos_lote.sucursal_id = {branch_id}\n"
        f"- organizacion_equipocliente:   JOIN organizacion_cliente\n"
        f"                                ON organizacion_equipocliente.cliente_id = organizacion_cliente.id\n"
        f"                                WHERE organizacion_cliente.sucursal_id = {branch_id}\n"
        f"- organizacion_sucursal:        WHERE id = {branch_id} (solo tu propia sucursal)\n"
        f"\n"
        f"Tablas globales (no filtrar por sucursal): productos_producto, productos_equipo, productos_marca, productos_categor\u00eda, productos_proveedor\n"
    )


def _build_schema_info(engine):
    metadata = MetaData()
    metadata.reflect(bind=engine)

    lines = []
    for table in metadata.sorted_tables:
        if table.name not in TABLAS_PERMITIDAS:
            continue
        cols = [
            f"  - {c.name} ({c.type})"
            for c in table.columns
            if c.name not in PII_COLUMNAS
        ]
        lines.append(f"Tabla: {table.name}\n" + "\n".join(cols))

    return "\n\n".join(lines)


@lru_cache(maxsize=20)
def obtener_agente(branch_id=None):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY no configurada en el entorno.')

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0
    )

    engine = create_engine(
        os.getenv('DATABASE_URL'),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )
    schema_info = _build_schema_info(engine)

    branch_rules = _build_branch_rules(branch_id) if branch_id else ""

    prefix = (
        f"Eres un asistente de base de datos para PrintPOS, un sistema de control de inventario.\n"
        f"El schema de las tablas relevantes es:\n\n{schema_info}\n\n"
        f"{branch_rules}\n"
        f"Genera únicamente consultas SELECT. No modifiques datos bajo ninguna circunstancia.\n"
        f"Responde en español de forma clara y concisa, basándote en los resultados de las consultas.\n"
        f"Responde únicamente en texto plano, sin usar formato markdown, JSON, ni ningún otro formato estructurado."
    )

    db = SQLDatabase(engine, include_tables=list(TABLAS_PERMITIDAS))
    toolkit = _RestrictedSQLDatabaseToolkit(db=db, llm=llm)

    return create_sql_agent(
        llm=llm,
        toolkit=toolkit,
        prefix=prefix,
        verbose=True,
        agent_executor_kwargs={
            "handle_parsing_errors": (
                "Tu respuesta no pudo ser interpretada. "
                "Responde ÚNICAMENTE con texto plano en español, "
                "sin ningún formato especial, ni JSON, ni markdown, ni bloques de código."
            ),
            "max_iterations": 10,
            "max_execution_time": 60.0,
            "early_stopping_method": "generate",
        },
    )
