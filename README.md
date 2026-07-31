# Bitcoin Paper Bot

Aplicación de escritorio educativa para macOS que simula operaciones de Bitcoin
con dinero ficticio. No se conecta a ningún exchange y no puede mover dinero real.

## Funciones

- Precio de BTC simulado localmente.
- Precio acotado entre 20.000 € y 200.000 €, con reversión gradual hacia
  90.000 € para evitar tendencias exponenciales irreales.
- Cartera inicial de 10.000 €.
- Compras y ventas manuales.
- Tras tres bajadas guarda una referencia y compra al encontrar un precio inferior,
  aunque haya oscilaciones entre medias.
- Cada lote se vende automáticamente al alcanzar un beneficio neto del 2,5 %.
- Botones de compra manual del 20 % y del 50 %.
- Límite normal del 20 % por compra.
- Puede efectuar compras sucesivas sin esperar a vender.
- Conserva siempre un mínimo de 2.000 € en efectivo.
- No realiza compras inferiores a 500 €; con 2.200 € de efectivo, por ejemplo,
  no compra porque solo quedarían 200 € disponibles sobre la reserva.
- Exposición máxima del 80 % de la cartera.
- Calcula el coste medio real de las compras.
- Simula comisiones y deslizamiento tanto al comprar como al vender.
- El objetivo de venta se calcula después de esos costes.
- Muestra beneficio realizado y pendiente, comisiones y caída máxima.
- Pausa nuevas compras cuando alcanza el límite de caída configurado.
- Guarda automáticamente la cartera, el historial y la configuración.
- Permite cambiar porcentajes, ciclos, costes, reserva y protección desde la app.
- Ejecuta backtests sobre hasta tres años de velas diarias públicas BTC-EUR de Coinbase.
- Compara la estrategia con comprar y mantener, y muestra aciertos y rentabilidad anualizada.
- Marca compras y ventas directamente sobre el gráfico de precios.
- Explica por qué el bot compra, espera o bloquea una operación.
- Permite reiniciar con confirmación el saldo, BTC, histórico y precio simulado.
- Mientras el bot automático está activo, evita el reposo inactivo de macOS;
  la pantalla sí puede apagarse.
- Las referencias de compra caducan después de cinco minutos de forma
  predeterminada para evitar bloqueos; este tiempo es configurable.
- Panel visual con tarjetas de métricas, pestañas, gráfico sombreado, indicador
  de riesgo y estados diferenciados por color.
- Si una posición cae más del 10 %, sus lotes existentes quedan congelados.
- Tras 15 ciclos dentro de un rango máximo del 1 %, el bot puede crear lotes
  nuevos de recuperación y operar solo con ellos; los lotes antiguos no se
  venden. Los tres valores son configurables.
- Cada compra mantiene su propio coste y objetivo neto del 2,5 %.
- Las ventas automáticas no esperan ciclos de subida: en cada actualización se
  venden únicamente los lotes que ya alcanzaron su objetivo, manteniendo
  abiertos los lotes más caros o congelados.

El histórico de Coinbase puede contener intervalos sin datos y un backtest no
predice resultados futuros.

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
