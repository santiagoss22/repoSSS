# Bitcoin Paper Bot · 1 Lote

Variante independiente para macOS que simula operaciones de Bitcoin con un único
lote. Invierte todo el efectivo disponible salvo una reserva fija de 2.000 €.
No puede mover dinero real.

## Funciones

- Precio de BTC simulado localmente.
- Selector entre mercado simulado y datos públicos BTC/EUR de Binance o Coinbase.
- Precio, bid, ask y velas en vivo mediante WebSocket de CCXT.
- Histórico OHLCV local en SQLite para `5m`, `1h` y `1d`.
- La estrategia en vivo decide únicamente al cerrar una vela de una hora.
- Bloquea nuevas compras si los datos llevan 30 segundos sin actualizarse o
  si el spread supera el límite configurado.
- Precio acotado entre 20.000 € y 200.000 €, con reversión gradual hacia
  90.000 € para evitar tendencias exponenciales irreales.
- Cartera inicial de 10.000 €.
- Compras y ventas manuales.
- Filtra la tendencia diaria con EMA 50/200 y busca retrocesos mediante RSI,
  Bandas de Bollinger y mejora del MACD en velas de una hora.
- Exige al menos dos de tres condiciones y confirmación EMA 9/21 en cinco minutos.
- Calcula ATR y bloquea señales con volatilidad extrema.
- El único lote se vende automáticamente al alcanzar el take-profit neto configurado
  (4 % de forma predeterminada).
- Un botón compra todo el efectivo que exceda la reserva fija.
- Solo puede existir un lote abierto; hay que venderlo antes de volver a comprar.
- Conserva siempre un mínimo de 2.000 € en efectivo.
- No realiza compras inferiores a 500 €; con 2.200 € de efectivo, por ejemplo,
  no compra porque solo quedarían 200 € disponibles sobre la reserva.
- Exposición limitada por la reserva fija de 2.000 €.
- Máximo estricto de un lote abierto.
- Calcula el coste medio real de las compras.
- Simula comisiones y deslizamiento tanto al comprar como al vender.
- El objetivo de venta se calcula después de esos costes.
- Stop-loss del 2 % y trailing stop del 1,5 % cuando la ganancia alcanza 2,5 %.
- Venta defensiva desde una pérdida del 1 % tras cinco confirmaciones
  bajistas consecutivas de EMA y MACD.
- Detecta un suelo estable durante 20 ciclos y vende un lote con pérdida si un
  rebote mínimo del 1,5 % vuelve a girarse a la baja.
- Tras vender espera 30 ciclos; permite reentrar después de un retroceso del 2 %
  con confirmación técnica. Una consolidación superior actualiza la referencia.
- Entre compras espera 15 ciclos y admite entradas más altas cuando EMA y al
  menos dos indicadores confirman la señal.
- Cooldown de 120 ciclos después de una salida por pérdida.
- Pausa automática al perder un 3 % diario o un 6 % semanal.
- Se detiene tras dos pérdidas consecutivas o un drawdown del 10 %.
- Guarda automáticamente la cartera, el historial y la configuración.
- Permite cambiar porcentajes, ciclos, costes, reserva y protección desde la app.
- Ejecuta backtests sobre hasta tres años de velas diarias públicas BTC-EUR de Coinbase.
- Compara la estrategia con comprar y mantener, y muestra aciertos y rentabilidad anualizada.
- Marca compras y ventas directamente sobre el gráfico de precios.
- Mantiene en el lateral el precio de cada lote abierto y su diferencia porcentual.
- Explica por qué el bot compra, espera o bloquea una operación.
- Permite reiniciar con confirmación el saldo, BTC, histórico y precio simulado.
- Mientras el bot automático está activo, evita el reposo inactivo de macOS;
  la pantalla sí puede apagarse.
- Panel simplificado con cuatro métricas esenciales y estado de riesgo compacto.
- Dibuja en el gráfico los niveles de entrada, stop-loss y take-profit.
- Cada compra mantiene su propio coste, máximo alcanzado, stop y objetivo.
- Las ventas automáticas no esperan ciclos de subida: cada actualización comprueba
  take-profit, stop-loss y trailing stop por lote.

El histórico de Coinbase puede contener intervalos sin datos y un backtest no
predice resultados futuros.

Los feeds de mercado son públicos y no requieren claves. El modo de mercado real
sigue operando exclusivamente con dinero simulado: no envía órdenes al exchange.

## Funcionamiento con la pantalla apagada

Al activar **Bot automático**, la aplicación inicia el mecanismo estándar
`caffeinate` de macOS para impedir que el sistema entre en reposo por
inactividad. La pantalla puede apagarse o bloquearse y el bot seguirá
simulando. Al desactivar el bot o cerrar la aplicación, esta protección termina.

El programa no puede ejecutarse durante un apagado, reinicio, cierre de sesión
o pérdida de alimentación.
- Historial de operaciones y beneficio/pérdida.

## Ejecutar en macOS

Necesitas Python 3.10 o posterior.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m bitcoin_bot
```

## Ejecutar las pruebas

```bash
python -m unittest discover -s tests
```

> Este proyecto es una simulación educativa, no asesoramiento financiero.
