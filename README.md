<h1 align="center">QASL-TDM</h1>

<p align="center">
  <strong>Test Data Management para Quality Engineering, orientado a banca.</strong><br>
  El test pide una condición de negocio. El TDM entrega un dato válido,<br>
  se lo reserva mientras dura la prueba y lo recupera al terminar.
</p>

<p align="center">
  <a href="https://github.com/E-Gregorio/qasl-tdm/actions/workflows/tests.yml">
    <img alt="tests" src="https://github.com/E-Gregorio/qasl-tdm/actions/workflows/tests.yml/badge.svg">
  </a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white">
  <img alt="motores" src="https://img.shields.io/badge/motores-SQLite%20%7C%20PostgreSQL-336791?logo=postgresql&logoColor=white">
  <img alt="tests" src="https://img.shields.io/badge/tests-45-2f7256">
  <a href="LICENSE"><img alt="licencia" src="https://img.shields.io/badge/licencia-MIT-0f172a"></a>
</p>

---

![Arquitectura de QASL-TDM](docs/arquitectura.png)

---

```python
with tdm.scenario("transferencia_exitosa") as cliente:
    page.fill("#cuenta", cliente["cuenta"])
    page.fill("#monto", "1000")
    page.click("#confirmar")
```

Eso es todo lo que ve quien automatiza. Sin SQL en el test, sin DNIs
hardcodeados, sin una planilla de cuentas compartida por chat, sin limpieza
manual. Si el bloque falla, el dato se libera igual.

---

## Índice

- [El problema](#el-problema)
- [Arranque rápido](#arranque-rápido)
- [Recorrido guiado](#recorrido-guiado)
- [El ciclo de vida](#el-ciclo-de-vida)
- [Decisiones de diseño](#decisiones-de-diseño)
- [Datos bancarios válidos](#datos-bancarios-válidos)
- [Escenarios](#escenarios)
- [Consumo desde la automatización](#consumo-desde-la-automatización)
- [Cumplimiento normativo](#cumplimiento-normativo)
- [Operación](#operación)
- [PostgreSQL](#postgresql)
- [Tests](#tests)
- [Estructura](#estructura)
- [Alcance y limitaciones](#alcance-y-limitaciones)
- [Licencia](#licencia)

---

## El problema

Un test no falla solamente porque el código esté mal. Falla porque no hay un
cliente con las condiciones que el caso necesita, porque otro equipo ya lo usó
y le cambió el estado, porque refrescaron el ambiente, o porque hay que esperar
tres días a que alguien lo cree.

La evidencia de que esto importa no es anecdótica. En un sistema industrial
estudiado en **ICSE-SEIP'26**, la contención de datos de prueba compartidos era
la causa principal de flakiness. Al resolverla con aislamiento y limpieza
explícita, el pass rate del pipeline pasó de **27% a 95%** y la capacidad de
release mensual de **60% a 96%**.

QASL-TDM ataca exactamente esa contención.

---

## Arranque rápido

**Requisitos:** Python 3.12 o superior. Nada más — arranca sobre SQLite.

```bash
git clone https://github.com/E-Gregorio/qasl-tdm.git
cd qasl-tdm

python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

python cli.py seed-all --count 50
python cli.py stats

uvicorn app.main:app --reload
```

Documentación interactiva en **http://127.0.0.1:8000/docs**.

Primera reserva:

<details>
<summary><strong>bash / macOS / Linux</strong></summary>

```bash
curl -X POST http://127.0.0.1:8000/tdm/reserve \
  -H "Content-Type: application/json" \
  -d '{"scenario":"transferencia_exitosa","reserved_by":"worker-1"}'
```
</details>

<details>
<summary><strong>PowerShell</strong></summary>

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/tdm/reserve -Method Post `
  -ContentType "application/json" `
  -Body '{"scenario":"transferencia_exitosa","reserved_by":"worker-1"}'
```

> En PowerShell `curl` es un alias de `Invoke-WebRequest` y no acepta la
> sintaxis `-H` / `-d` de bash.
</details>

---

## Recorrido guiado

La forma más rápida de entender qué hace un TDM. Con la API levantada en otra
terminal:

```bash
python demo.py
```

Ejecuta el ciclo completo paso a paso, explicando cada uno y esperando `Enter`
entre pasos:

| Paso | Qué demuestra |
|---|---|
| 1 · Estado del pool | El inventario: qué hay y en qué estado |
| 2 · SEED | Dónde **nacen** los datos, a partir de una condición de negocio |
| 3 · RESERVE | Un test pide un dato. No se crea nada: es un `SELECT` + un `UPDATE` |
| 4 · Concurrencia | Dos workers piden a la vez y reciben registros distintos |
| 5 · Dueño | Un worker no puede liberar el dato de otro |
| 6 · RELEASE | Devolverlo limpio, o marcarlo sucio si el test lo modificó |
| 7 · RESET | Recuperar el dato sucio sin alterar la identidad del cliente |
| 8 · Auditoría | Quién lo tocó, cuándo y para qué |
| 9 · EXPORT | El CSV de volumen para JMeter, sin quemar datos entre corridas |

También hay una versión navegable de la arquitectura en
[`docs/arquitectura.html`](docs/arquitectura.html).

---

## El ciclo de vida

```
        MITAD BATCH                          MITAD RUNTIME
   (corre en un job, nadie espera)      (responde a cada test, en ms)

   SEED / LOAD                                RESERVE
        |                                        |
      MASK                                      USE
        |                                        |
     REFRESH  <------------------------  RELEASE / RESET
```

Las dos mitades tienen ritmos distintos y por eso viven en módulos separados:
`pool_service` corre por lotes, `reservation_service` responde en línea.
Mezclarlas produce un sistema que ni refresca bien ni responde rápido.

| Etapa | Qué hace | Endpoint |
|---|---|---|
| **SEED** | Genera datos sintéticos que cumplen el escenario | `POST /tdm/pool/seed` |
| **LOAD** | Carga datos preparados afuera (DB2, CSV, API) | `POST /tdm/pool/load` |
| **MASK** | Enmascara lo sensible, determinístico y preservando formato | `POST /tdm/records/{id}/mask` |
| **RESERVE** | Entrega un dato y lo saca de circulación, con TTL | `POST /tdm/reserve` |
| **RELEASE** | Lo devuelve al pool (`CLEAN`) o lo marca sucio (`DIRTY`) | `POST /tdm/release` |
| **RESET** | Restaura la condición de negocio del dato sucio | `POST /tdm/reset/{id}` |
| **REFRESH** | Expira vencidos, limpia sucios y repone hasta el mínimo | `POST /tdm/pool/refresh` |
| **EXPORT** | Extracción masiva a CSV para JMeter | `GET /tdm/pool/export` |

---

## Decisiones de diseño

Las cuatro que separan un TDM de un CRUD con nombre elegante.

### 1 · La unidad de reserva es el escenario, no la entidad

Un registro trae cliente, cuenta, tarjeta y condición de negocio en una sola
fila. Si se reservaran piezas sueltas —primero el cliente, después la cuenta—
habría interbloqueos el primer día: el test A toma el cliente y espera la
cuenta, el test B al revés.

### 2 · La reserva es atómica, y el cómo depende del motor

En **PostgreSQL** se usa `SELECT ... FOR UPDATE SKIP LOCKED`: cada worker toma
una fila distinta sin esperar a los demás.

**SQLite** no tiene `SKIP LOCKED`, así que se usa un `UPDATE` condicional con
reintentos: se marca la fila solo si sigue en `AVAILABLE` y se verifica el
`rowcount`. Si otro worker ganó la carrera, el rowcount es 0 y se reintenta.

```python
UPDATE test_data
SET status = 'RESERVED', reserved_by = ?, expires_at = ?
WHERE id = ? AND status = 'AVAILABLE'    -- <- esta condición es la garantía
```

`tests/test_concurrency.py` verifica que doce workers concurrentes reciben doce
registros distintos, y que con más workers que datos sobran workers en lugar de
duplicarse entregas. **La suite corre en CI sobre los dos motores.**

### 3 · Una reserva vencida no vuelve al pool: pasa a DIRTY

Si un test murió a mitad de camino, no sabemos qué le hizo al dato. Devolverlo a
`AVAILABLE` sin revisarlo es exactamente como se contaminan los ambientes de QA.
El dato vencido queda fuera de circulación hasta que `RESET` le restaura la
condición de negocio.

`RESET` **no cambia la identidad** del cliente —DNI, CUIT, CBU, tarjeta— porque
un test que guardó el CBU para verificar después dejaría de encontrarlo. Lo que
se regenera es el saldo, el estado de cuenta y los días de mora.

### 4 · El enmascaramiento preserva el formato

Un DNI enmascarado como `****6789` no se puede tipear en un formulario ni pasa
una validación: el test muere antes de llegar a la lógica que quería probar.

| Propiedad | Por qué | Test |
|---|---|---|
| **Preserva formato** | El CBU conserva sus verificadores, la tarjeta sigue pasando Luhn | `test_el_dato_enmascarado_sigue_siendo_valido` |
| **Es determinístico** | El mismo DNI da siempre el mismo valor; sin esto se rompe la integridad referencial entre tablas | `test_es_deterministico` |
| **Es idempotente** | Enmascarar dos veces no vuelve a enmascarar | `test_es_idempotente_via_api` |
| **Es verosímil** | El DNI resultante cae en el rango real argentino | `test_el_dni_enmascarado_queda_en_rango_real` |

Se conservan banco, sucursal y BIN: identifican a la entidad emisora, no a la
persona, y mantenerlos hace que el dato siga siendo realista.

---

## Datos bancarios válidos

Todo identificador se genera con su dígito verificador correcto, y la suite lo
verifica cruzándolo contra **[python-stdnum](https://arthurdejong.org/python-stdnum/)**,
una librería independiente:

| Identificador | Algoritmo |
|---|---|
| **CUIT / CUIL** | Módulo 11, ponderadores 5-4-3-2-7-6-5-4-3-2 |
| **CBU** | Dos bloques, ponderadores cíclicos 3-1-7-9 |
| **PAN** | Luhn (ISO/IEC 7812-1) |

```python
>>> from app.services.generator_service import GeneratorService
>>> r = GeneratorService().generate("transferencia_exitosa", 1, seed=42)[0]
>>> from stdnum.ar import cbu, cuit
>>> cbu.is_valid(r["cuenta"]), cuit.is_valid(r["cuit"])
(True, True)
```

Un `seed` fijo hace la generación reproducible: el mismo seed produce el mismo
lote. Eso es lo que permite reproducir un fallo de test.

---

## Escenarios

| Escenario | Condición de negocio |
|---|---|
| `transferencia_exitosa` | Cliente activo con saldo suficiente para transferir |
| `saldo_insuficiente` | Cliente activo sin fondos para operar |
| `cuenta_bloqueada` | Cuenta con saldo pero bloqueada operativamente |
| `cuenta_cerrada` | Cuenta dada de baja |
| `cliente_con_mora` | Cliente con mora mayor a 90 días |
| `transferencia_usd` | Cuenta en dólares con saldo suficiente |

Se agregan en [`app/services/generator_service.py`](app/services/generator_service.py)
declarando la condición. No hace falta tocar nada más:

```python
"mi_escenario": ScenarioSpec(
    name="mi_escenario",
    description="...",
    saldo_min=100_000,
    saldo_max=5_000_000,
    estado_cuenta=AccountState.ACTIVA,
),
```

---

## Consumo desde la automatización

### SDK con context manager

```python
from sdk import QaslTdmClient

tdm = QaslTdmClient("http://localhost:8000")

with tdm.scenario("transferencia_exitosa") as cliente:
    ...
```

Si el bloque lanza excepción, el dato se libera como **DIRTY**. No se puede
asumir que un test que explotó dejó el dato intacto.

### Plugin de pytest

En el `conftest.py` del proyecto de automatización:

```python
pytest_plugins = ["sdk.pytest_plugin"]
```

Y después:

```python
def test_transferencia(tdm_scenario):
    cliente = tdm_scenario("transferencia_exitosa")
    ...
```

La fixture libera todo al terminar, y marca `DIRTY` si el test falló.

### JMeter

Las pruebas de carga necesitan **volumen precargado**, no datos on-demand: pedir
un registro por iteración convertiría al TDM en el cuello de botella de la
propia prueba.

```bash
python cli.py export transferencia_exitosa \
  --limit 10000 --out carga.csv --reserve-for corrida-001
```

`--reserve-for` reserva los registros exportados. Eso resuelve el problema
clásico: los datos se queman en la primera corrida y la segunda da falsos
negativos porque reutiliza registros ya consumidos. La segunda corrida recibe un
conjunto distinto, y `test_export_con_reserva_no_quema_los_datos_dos_veces` lo
verifica.

En JMeter se consume con **CSV Data Set Config** apuntando a ese archivo.

---

## Cumplimiento normativo

Dos requisitos concretos que este diseño cubre:

**PCI-DSS v4.0, requisito 6.5.5** — prohíbe PANs reales en entornos de
pre-producción salvo que el entorno entre al CDE con todos sus controles. Por
eso `SEED` y `LOAD` enmascaran **por defecto**: el camino fácil tiene que ser el
que cumple.

**BCRA, Comunicación "A" 7724, punto 9.2.2** — exige *"documentar el diseño,
creación y preparación de datos de prueba que consideren la protección de datos
personales o sensibles"*. La tabla `audit_log` es esa documentación, y se genera
sola:

```
GET /tdm/records/{id}/audit
```

Devuelve quién tocó el registro, cuándo y para qué: `SEED`, `MASK`, `RESERVE`,
`RELEASE`, `RESET`, `EXPIRE`, `EXPORT`.

---

## Operación

```bash
python cli.py scenarios                 # catálogo de escenarios
python cli.py seed-all --count 50       # carga inicial del pool
python cli.py seed transferencia_exitosa --count 500 --seed 42
python cli.py stats                     # tablero del pool
python cli.py refresh --min 50          # expira, limpia y repone
python cli.py expire                    # solo libera reservas vencidas
python cli.py export transferencia_exitosa --limit 10000 --out carga.csv
```

`refresh` es lo que corre un job nocturno o un step de pipeline.

### Configuración

Todo por variables de entorno. Ver [`.env.example`](.env.example).

| Variable | Por defecto | Para qué |
|---|---|---|
| `QASL_TDM_DATABASE_URL` | SQLite local | Motor de base de datos |
| `QASL_TDM_MASKING_SALT` | valor de laboratorio | Semilla del enmascaramiento |
| `QASL_TDM_DEFAULT_TTL` | `300` | Vida útil de una reserva, en segundos |
| `QASL_TDM_POOL_MIN` | `20` | Mínimo por escenario que mantiene `refresh` |

> La sal del enmascaramiento define el mapeo de valores. En un entorno real vive
> en un secret manager, nunca en el repositorio.

---

## PostgreSQL

```bash
docker compose up -d
pip install "psycopg[binary]"

export QASL_TDM_DATABASE_URL="postgresql+psycopg://qasl:qasl@localhost:5432/qasl_tdm"
python cli.py init
python cli.py seed-all --count 200
```

Con PostgreSQL la reserva usa `FOR UPDATE SKIP LOCKED` automáticamente; no hay
que cambiar nada en el código.

---

## Tests

```bash
pytest
```

45 tests, base aislada que se borra al terminar. **El pipeline corre la misma
suite sobre SQLite (Python 3.12 y 3.13) y sobre PostgreSQL 16**, de modo que
ambos caminos de reserva quedan ejercitados.

| Archivo | Qué verifica |
|---|---|
| `test_banking.py` | Los identificadores generados pasan la validación de python-stdnum |
| `test_masking.py` | Formato preservado, determinismo, idempotencia, integridad referencial |
| `test_masking_range.py` | El dato enmascarado es verosímil, no solo sintácticamente válido |
| `test_lifecycle.py` | El ciclo completo vía API, incluida la expiración a `DIRTY` |
| `test_concurrency.py` | Doce workers concurrentes, cero entregas duplicadas |
| `test_sdk.py` | El context manager libera siempre, incluso con el test fallando |

Para correr la suite contra PostgreSQL en local:

```bash
docker compose up -d
QASL_TDM_DATABASE_URL="postgresql+psycopg://qasl:qasl@localhost:5432/qasl_tdm" pytest
```

---

## Estructura

```
app/
  config.py                    Variables de entorno
  database.py                  Engine, detección de motor, PRAGMAs de SQLite
  main.py                      Aplicación FastAPI
  models/
    enums.py                   Estados del ciclo de vida
    db.py                      PoolRecord, AuditLog
    schemas.py                 Contratos de la API
  services/
    banking.py                 CUIT, CBU y Luhn
    generator_service.py       Escenarios declarativos y generación
    masking_service.py         Enmascaramiento determinista
    pool_service.py            SEED, LOAD, REFRESH, STATS, EXPORT
    reservation_service.py     RESERVE, RELEASE, RESET, EXPIRE
    tdm_service.py             Alta y consulta individual
    audit_service.py           Bitácora
  api/
    deps.py, records.py, pool.py, reservations.py
sdk/
  client.py                    Cliente Python
  pytest_plugin.py             Fixtures tdm_client y tdm_scenario
cli.py                         Operación batch
demo.py                        Recorrido narrado del ciclo
docs/                          Arquitectura (PNG y HTML navegable)
examples/                      Cómo lo consume una suite de automatización
tests/                         Suite del proyecto
```

---

## Alcance y limitaciones

Lo que este proyecto **no** hace, dicho explícitamente:

- **No extrae de producción.** `LOAD` recibe registros ya extraídos. En un banco
  esa extracción la hace la entidad, con sus permisos y herramientas.
- **No hay subsetting.** Un subconjunto coherente de una base productiva es otro
  problema, y está resuelto comercialmente.
- **No hay conectores a DB2 ni a Oracle.** El punto de integración es `LOAD`.
- **No hay autenticación.** El servicio asume red interna. Es lo primero del
  roadmap.
- **La expiración es perezosa.** Se procesa al reservar o al llamar a
  `POST /tdm/expire`; no hay un proceso de fondo mirando el reloj. En operación
  eso lo cubre un job periódico.
- **`RESET` regenera la condición de negocio dentro del pool.** No revierte
  cambios que el test haya hecho en el sistema bajo prueba.

### Roadmap

- [ ] Autenticación y autorización
- [ ] Logs estructurados y métricas
- [ ] Conectores de extracción (DB2, Oracle)
- [ ] Interfaz web de operación del pool

---

## Sobre el alcance del módulo

QASL-TDM forma parte del ecosistema QASL. Su intención es acotada y deliberada:
no es una plataforma TDM empresarial, es el **runtime de datos que consume el
framework de automatización**. Las capacidades que ya están resueltas por el
mercado —masking industrial, subsetting, virtualización— no se intentan
replicar.

---

## Licencia

[MIT](LICENSE) · **Elyer Gregorio Maldonado**

[LinkedIn](https://linkedin.com/in/elyergregorio) ·
[GitHub](https://github.com/E-Gregorio) ·
[Portafolio](https://e-gregorio.github.io/mi-portafolio/qasl-platform.html)

> Los datos que genera este proyecto son sintéticos. Los códigos de banco y los
> BIN de tarjeta son ficticios y no corresponden a entidades reales.
