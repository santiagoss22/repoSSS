# Bots Trading · Bitcoin Paper Trading

Aplicación educativa para macOS que compara estrategias de trading de Bitcoin
con dinero ficticio. Nunca envía órdenes reales ni utiliza claves privadas de
un exchange.

## Estrategias incluidas

- **bot-RSIs**: RSI(6/12/24), EMA(9/50/200) y MACD sobre velas cerradas de 1h.
- **bot-Envolvente-BOS**: vela envolvente, quiebre de estructura y retesteo
  posterior del nivel roto.

Cada estrategia abre una interfaz y un proceso independientes. Sus saldos,
operaciones, configuración e histórico se guardan por separado. El selector
permite ejecutar ambas simultáneamente para comparar sus simulaciones.

## Organización

```text
repoSSS/
├── Abrir simulador de bots.command
├── launcher.py
├── bots/
│   ├── bot-RSIs/
│   │   ├── strategy.py
│   │   └── README.md
│   └── bot-Envolvente-BOS/
│       ├── strategy.py
│       └── README.md
├── bitcoin_bot/              # motor e interfaz compartidos
│   ├── simulator.py
│   ├── market_data.py
│   ├── backtest.py
│   ├── persistence.py
│   ├── strategy_loader.py
│   └── ui.py
└── tests/
```

Las ramas se utilizan para desarrollar y revisar cambios; las estrategias
terminadas permanecen como carpetas dentro de la rama principal.

## Abrir en macOS

Haz doble clic en `Abrir simulador de bots.command`. La primera ejecución crea
el entorno e instala las dependencias. Después elige un bot o abre los dos.

También puedes iniciar directamente una estrategia:

```bash
BOT_STRATEGY=bot-RSIs python -m bitcoin_bot
BOT_STRATEGY=bot-Envolvente-BOS python -m bitcoin_bot
```

## Protecciones compartidas

- Saldo inicial simulado de 10.000 € y reserva de 2.000 €.
- Hasta ocho lotes automáticos de 1.000 €.
- Riesgo, stop-loss, objetivo y trailing adaptados al ATR por lote.
- Comisiones y slippage simulados.
- Límites diario, semanal, por drawdown y por racha de pérdidas.
- Datos públicos de Kraken y replay histórico; no se requieren claves API.
- Backtest con esperanza, Sharpe, Sortino, exposición, estrés de costes y
  Monte Carlo.

## Pruebas

```bash
python -m unittest discover -s tests
```

Los resultados históricos no garantizan rentabilidad futura. Este proyecto no
es asesoramiento financiero.
