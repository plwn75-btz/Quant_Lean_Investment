# QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
# Lean Algorithmic Trading Engine v2.0. Copyright 2014 QuantConnect Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from AlgorithmImports import *
from collections import deque

### <summary>
### Multi-Signal Strategy — translates AmiBroker-style buy/sell conditions into LEAN indicators.
###
### BUY CONDITIONS (BCOND1–BCOND13):
###   BCOND1  = EMA50 > EMA200 (uptrend — use alone or with BCOND9/BCOND12)
###   BCOND2  = BuyVolume > vol-ratio * SellVolume
###   BCOND3  = RSI(14) < rsi-oversold  (oversold — do NOT combine with BCOND10)
###   BCOND4  = Close crossed above ParabolicSAR
###   BCOND5  = ADX(14) < adx-threshold  (non-trending)
###   BCOND6  = PDI(14) > MDI(14)
###   BCOND7  = PDI(14) > pdi-threshold
###   BCOND8  = 52-week high within h52w-margin of safety
###   BCOND9  = MACD(12,26) > 0  (momentum bullish)
###   BCOND10 = StochK(14,3) > stoch-buy-thr  (NOTE: do NOT combine with BCOND3)
###   BCOND11 = Close > ParabolicSAR
###   BCOND12 = Close > Bollinger Band Mid
###   BCOND13 = BigGapUp (today's Low > 1+gap-up-pct * yesterday's High)
###
### SELL CONDITIONS (SCOND1–SCOND12):
###   SCOND1  = EMA200 > EMA50  (trend reversal)
###   SCOND2  = EMA13 crossed above EMA200
###   SCOND3  = RSI(14) > rsi-overbought  (overbought)
###   SCOND5  = ADX(14) > adx-threshold  (strong trend)
###   SCOND6  = PDI(14) < MDI(14)  (bears dominate)
###   SCOND7  = Price more than l52w-margin above 52-week low
###   SCOND9  = MACD(12,26) < 0  (momentum bearish)
###   SCOND10 = StochK(14,3) < stoch-sell-thr
###   SCOND11 = EMA13 < EMA50 AND within ema-proximity
###   SCOND12 = BigGapDown (today's High < 1-gap-down-pct * yesterday's Low)
###
### Default active signals (non-contradictory — sensible momentum trend-follow):
###   Buy  = BCOND1 AND BCOND9 AND BCOND12
###   Sell = SCOND1 OR  SCOND9
### </summary>
class MultiSignalStrategy(QCAlgorithm):

    def initialize(self):
        # ── Backtest window ────────────────────────────────────────────────
        start_year  = int(self.get_parameter("start-year",  "2016"))
        start_month = int(self.get_parameter("start-month", "1"))
        start_day   = int(self.get_parameter("start-day",   "1"))
        end_year    = int(self.get_parameter("end-year",    "2023"))
        end_month   = int(self.get_parameter("end-month",   "12"))
        end_day     = int(self.get_parameter("end-day",     "31"))

        self.set_start_date(start_year, start_month, start_day)
        self.set_end_date(end_year, end_month, end_day)

        # ── Capital & position sizing ──────────────────────────────────────
        initial_cash    = float(self.get_parameter("initial-cash",    "100000"))
        self._position_size = float(self.get_parameter("position-size", "1.0"))  # fraction of portfolio
        self.set_cash(initial_cash)

        # ── Symbol ─────────────────────────────────────────────────────────
        ticker = self.get_parameter("ticker", "GOOG")
        self._symbol = self.add_equity(ticker, Resolution.DAILY).symbol

        # ── Indicator periods (all parameterised) ──────────────────────────
        self._ema13_period  = int(self.get_parameter("ema13-period",  "13"))
        self._ema50_period  = int(self.get_parameter("ema50-period",  "50"))
        self._ema200_period = int(self.get_parameter("ema200-period", "200"))
        self._rsi_period    = int(self.get_parameter("rsi-period",    "14"))
        self._adx_period    = int(self.get_parameter("adx-period",    "14"))
        self._macd_fast     = int(self.get_parameter("macd-fast",     "12"))
        self._macd_slow     = int(self.get_parameter("macd-slow",     "26"))
        self._macd_signal   = int(self.get_parameter("macd-signal",   "9"))
        self._stoch_period  = int(self.get_parameter("stoch-period",  "14"))
        self._stoch_k       = int(self.get_parameter("stoch-k",       "3"))
        self._bb_period     = int(self.get_parameter("bb-period",     "15"))
        self._bb_width      = float(self.get_parameter("bb-width",    "2"))
        self._sar_acc       = float(self.get_parameter("sar-acc",     "0.02"))
        self._sar_max_acc   = float(self.get_parameter("sar-max-acc", "0.2"))
        self._avvol_period  = int(self.get_parameter("avvol-period",  "5"))
        self._hwks52_period = int(self.get_parameter("hwks52-period", "260"))
        self._lwks52_period = int(self.get_parameter("lwks52-period", "260"))

        # ── Condition thresholds ───────────────────────────────────────────
        self._rsi_oversold   = float(self.get_parameter("rsi-oversold",    "40"))
        self._rsi_overbought = float(self.get_parameter("rsi-overbought",  "65"))
        self._adx_threshold  = float(self.get_parameter("adx-threshold",   "25"))
        self._pdi_threshold  = float(self.get_parameter("pdi-threshold",   "30"))
        self._stoch_buy_thr  = float(self.get_parameter("stoch-buy-thr",   "70"))
        self._stoch_sell_thr = float(self.get_parameter("stoch-sell-thr",  "70"))
        self._vol_ratio      = float(self.get_parameter("vol-ratio",       "2"))
        self._ema_proximity  = float(self.get_parameter("ema-proximity",   "0.1"))
        self._h52w_margin    = float(self.get_parameter("h52w-margin",     "0.1"))
        self._l52w_margin    = float(self.get_parameter("l52w-margin",     "0.3"))
        self._gap_up_pct     = float(self.get_parameter("gap-up-pct",      "0.02"))
        self._gap_down_pct   = float(self.get_parameter("gap-down-pct",    "0.02"))

        # ── Active condition toggles (1 = enabled, 0 = disabled) ───────────
        # Default: BCOND1 (uptrend) + BCOND9 (MACD+) + BCOND12 (above BB mid)
        # WARNING: Do NOT enable BCOND3 (RSI<oversold) together with BCOND10
        # (StochK>70) — they are almost mutually exclusive.
        self._buy_conds = {
            1:  int(self.get_parameter("bcond1",  "1")),   # EMA50 > EMA200
            2:  int(self.get_parameter("bcond2",  "0")),
            3:  int(self.get_parameter("bcond3",  "0")),   # OFF by default (contradicts bcond10)
            4:  int(self.get_parameter("bcond4",  "0")),
            5:  int(self.get_parameter("bcond5",  "0")),
            6:  int(self.get_parameter("bcond6",  "0")),
            7:  int(self.get_parameter("bcond7",  "0")),
            8:  int(self.get_parameter("bcond8",  "0")),
            9:  int(self.get_parameter("bcond9",  "1")),   # MACD > 0
            10: int(self.get_parameter("bcond10", "0")),   # OFF by default (contradicts bcond3)
            11: int(self.get_parameter("bcond11", "0")),
            12: int(self.get_parameter("bcond12", "1")),   # Close > BB mid
            13: int(self.get_parameter("bcond13", "0")),
        }
        self._sell_conds = {
            1:  int(self.get_parameter("scond1",  "1")),   # EMA200 > EMA50
            2:  int(self.get_parameter("scond2",  "0")),
            3:  int(self.get_parameter("scond3",  "0")),
            5:  int(self.get_parameter("scond5",  "0")),
            6:  int(self.get_parameter("scond6",  "0")),
            7:  int(self.get_parameter("scond7",  "0")),
            9:  int(self.get_parameter("scond9",  "1")),   # MACD < 0
            10: int(self.get_parameter("scond10", "0")),
            11: int(self.get_parameter("scond11", "0")),
            12: int(self.get_parameter("scond12", "0")),
        }
        # Debug flag: log indicator values every N bars
        self._debug_every = int(self.get_parameter("debug-every", "0"))  # 0 = off
        self._bar_count = 0

        # ── Create indicators ──────────────────────────────────────────────
        self._ema13  = self.ema(self._symbol, self._ema13_period,  Resolution.DAILY)
        self._ema50  = self.ema(self._symbol, self._ema50_period,  Resolution.DAILY)
        self._ema200 = self.ema(self._symbol, self._ema200_period, Resolution.DAILY)
        self._rsi    = self.rsi(self._symbol, self._rsi_period,    MovingAverageType.WILDERS, Resolution.DAILY)
        self._adx    = self.adx(self._symbol, self._adx_period,    Resolution.DAILY)
        self._macd   = self.macd(self._symbol, self._macd_fast, self._macd_slow, self._macd_signal, MovingAverageType.EXPONENTIAL, Resolution.DAILY)
        self._stoch  = self.sto(self._symbol, self._stoch_period, self._stoch_k, self._stoch_k, Resolution.DAILY)
        self._bb     = self.bb(self._symbol, self._bb_period, self._bb_width, MovingAverageType.SIMPLE, Resolution.DAILY)
        self._psar   = self.psar(self._symbol, self._sar_acc, self._sar_acc, self._sar_max_acc, Resolution.DAILY)

        # Rolling-window max/min for 52-week High/Low
        self._max52 = self.max(self._symbol, self._hwks52_period, Resolution.DAILY)
        self._min52 = self.min(self._symbol, self._lwks52_period, Resolution.DAILY)

        # ── Previous-bar storage (for cross detection and gap checks) ───────
        self._prev_close  = None
        self._prev_high   = None
        self._prev_low    = None
        self._prev_ema50  = None
        self._prev_ema200 = None
        self._prev_ema13  = None
        self._prev_psar   = None
        self._prev_stoch_k = None

        # Volume rolling window for average volume (5-day)
        self._vol_window = deque(maxlen=self._avvol_period)

        # State: track whether we had a buy signal last bar (for ExRem logic)
        self._in_position = False
        self._last_buy_bar_open = False

        # Warm up to longest indicator
        warm_up = max(
            self._ema200_period,
            self._hwks52_period,
            self._lwks52_period,
        )
        self.set_warm_up(warm_up, Resolution.DAILY)

        # ── Custom chart ───────────────────────────────────────────────────
        price_chart = Chart("Price & Signals")
        price_chart.add_series(Series("Close",       SeriesType.LINE, 0))
        price_chart.add_series(Series("EMA50",       SeriesType.LINE, 0))
        price_chart.add_series(Series("EMA200",      SeriesType.LINE, 0))
        price_chart.add_series(Series("Buy Signal",  SeriesType.SCATTER, "$", Color.GREEN))
        price_chart.add_series(Series("Sell Signal", SeriesType.SCATTER, "$", Color.RED))
        self.add_chart(price_chart)

        signal_chart = Chart("Indicators")
        signal_chart.add_series(Series("RSI",     SeriesType.LINE, 1))
        signal_chart.add_series(Series("MACD",    SeriesType.LINE, 2))
        signal_chart.add_series(Series("StochK",  SeriesType.LINE, 3))
        signal_chart.add_series(Series("ADX",     SeriesType.LINE, 4))
        self.add_chart(signal_chart)

        self.log(f"MultiSignalStrategy initialized | ticker={ticker} | "
                 f"{start_year}-{start_month:02d}-{start_day:02d} → "
                 f"{end_year}-{end_month:02d}-{end_day:02d}")

    # ──────────────────────────────────────────────────────────────────────
    def on_data(self, data: Slice):
        if self.is_warming_up:
            return
        if not data.bars.contains_key(self._symbol):
            return

        bar = data.bars[self._symbol]
        close  = bar.close
        high   = bar.high
        low    = bar.low
        volume = bar.volume

        # Guard: indicators must be ready
        if not self._all_ready():
            self._update_prev(close, high, low)
            return

        # ── Derived values ─────────────────────────────────────────────────
        ema13  = self._ema13.current.value
        ema50  = self._ema50.current.value
        ema200 = self._ema200.current.value
        rsi    = self._rsi.current.value
        adx    = self._adx.current.value
        pdi    = self._adx.positive_directional_index.current.value
        mdi    = self._adx.negative_directional_index.current.value
        macd   = self._macd.current.value   # MACD line
        stoch_k = self._stoch.stoch_k.current.value
        bb_mid  = self._bb.middle_band.current.value
        psar    = self._psar.current.value
        max52   = self._max52.current.value
        min52   = self._min52.current.value

        # Volume-based buy/sell volume
        self._vol_window.append(volume)
        buy_vol  = 0 if (high == low) else volume * (close - low) / (high - low)
        sell_vol = 0 if (high == low) else volume * (high - close) / (high - low)

        # Gap detection (requires previous bar)
        big_gap_up   = False
        big_gap_down = False
        if self._prev_high is not None and self._prev_low is not None:
            big_gap_up   = low  > (1 + self._gap_up_pct)   * self._prev_high
            big_gap_down = high < (1 - self._gap_down_pct) * self._prev_low

        # EMA cross detection
        ema50_cross_above_200 = (self._prev_ema50 is not None and
                                  self._prev_ema50 <= self._prev_ema200 and
                                  ema50 > ema200)
        ema13_cross_above_200 = (self._prev_ema13 is not None and
                                  self._prev_ema13 <= self._prev_ema200 and
                                  ema13 > ema200)
        close_cross_above_psar = (self._prev_close is not None and
                                   self._prev_psar  is not None and
                                   self._prev_close <= self._prev_psar and
                                   close > psar)

        # ── Evaluate BUY conditions ────────────────────────────────────────
        bcond = {
            1:  (ema50_cross_above_200) or (ema50 > ema200),
            2:  buy_vol > self._vol_ratio * sell_vol,
            3:  rsi < self._rsi_oversold,
            4:  close_cross_above_psar,
            5:  adx < self._adx_threshold,
            6:  pdi > mdi,
            7:  pdi > self._pdi_threshold,
            8:  max52 > 0 and ((max52 - close) / close) <= self._h52w_margin,
            9:  macd > 0,
            10: stoch_k > self._stoch_buy_thr,
            11: close > psar,
            12: close > bb_mid,
            13: big_gap_up,
        }

        # ── Evaluate SELL conditions ───────────────────────────────────────
        scond = {
            1:  (ema200 > ema50) and (ema200 - ema50) / ema200 < self._ema_proximity,
            2:  ema13_cross_above_200,
            3:  rsi > self._rsi_overbought,
            5:  adx > self._adx_threshold,
            6:  pdi < mdi,
            7:  min52 > 0 and ((close - min52) / min52) > self._l52w_margin,
            9:  macd < 0,
            10: stoch_k < self._stoch_sell_thr,
            11: (ema13 < ema50) and (ema50 - ema13) / ema50 < self._ema_proximity,
            12: big_gap_down,
        }

        # ── Apply condition toggles → combine signals ──────────────────────
        # All enabled buy conditions must be True (AND logic)
        active_buy_conds  = [k for k, enabled in self._buy_conds.items()  if enabled]
        active_sell_conds = [k for k, enabled in self._sell_conds.items() if enabled]

        buy_signal  = all(bcond[k] for k in active_buy_conds)  if active_buy_conds  else False
        sell_signal = any(scond[k] for k in active_sell_conds) if active_sell_conds else False

        # ExRem equivalent: suppress consecutive buy signals while in position,
        # suppress consecutive sell signals while not in position
        if self._in_position:
            buy_signal = False   # already long
        else:
            sell_signal = False  # nothing to sell

        # ── Optional debug: log indicator snapshot every N bars ────────────
        self._bar_count += 1
        if self._debug_every > 0 and (self._bar_count % self._debug_every == 1 or buy_signal or sell_signal):
            failed_buy = [f"B{k}" for k in active_buy_conds if not bcond[k]]
            passed_buy = [f"B{k}" for k in active_buy_conds if  bcond[k]]
            self.log(
                f"DBG {self.time.date()} "
                f"C={close:.2f} EMA50={ema50:.2f} EMA200={ema200:.2f} "
                f"RSI={rsi:.1f} MACD={macd:.4f} "
                f"StochK={stoch_k:.1f} ADX={adx:.1f} PSAR={psar:.2f} "
                f"BBmid={bb_mid:.2f} "
                f"PASS={passed_buy} FAIL={failed_buy} "
                f"BUY={buy_signal} SELL={sell_signal} POS={self._in_position}"
            )

        # ── Execute orders ─────────────────────────────────────────────────
        holdings = self.portfolio[self._symbol].quantity

        if buy_signal and holdings <= 0:
            self.set_holdings(self._symbol, self._position_size)
            self._in_position = True
            self.plot("Price & Signals", "Buy Signal", close)
            active_names = [f"BCOND{k}" for k in active_buy_conds if bcond[k]]
            self.log(f"BUY  | {self.time.date()} | Close={close:.2f} | Active={active_names}")

        elif sell_signal and holdings > 0:
            self.liquidate(self._symbol)
            self._in_position = False
            self.plot("Price & Signals", "Sell Signal", close)
            active_names = [f"SCOND{k}" for k in active_sell_conds if scond[k]]
            self.log(f"SELL | {self.time.date()} | Close={close:.2f} | Active={active_names}")

        # ── Charting ───────────────────────────────────────────────────────
        self.plot("Price & Signals", "Close",  close)
        self.plot("Price & Signals", "EMA50",  ema50)
        self.plot("Price & Signals", "EMA200", ema200)
        self.plot("Indicators", "RSI",    rsi)
        self.plot("Indicators", "MACD",   macd)
        self.plot("Indicators", "StochK", stoch_k)
        self.plot("Indicators", "ADX",    adx)

        # ── Update previous-bar state ──────────────────────────────────────
        self._update_prev(close, high, low, ema13, ema50, ema200, psar, stoch_k)

    # ──────────────────────────────────────────────────────────────────────
    def _all_ready(self) -> bool:
        """Return True when all indicators have enough data."""
        return (self._ema13.is_ready  and
                self._ema50.is_ready  and
                self._ema200.is_ready and
                self._rsi.is_ready    and
                self._adx.is_ready    and
                self._macd.is_ready   and
                self._stoch.is_ready  and
                self._bb.is_ready     and
                self._psar.is_ready   and
                self._max52.is_ready  and
                self._min52.is_ready)

    def _update_prev(self, close, high, low,
                     ema13=None, ema50=None, ema200=None,
                     psar=None, stoch_k=None):
        self._prev_close  = close
        self._prev_high   = high
        self._prev_low    = low
        if ema13  is not None: self._prev_ema13  = ema13
        if ema50  is not None: self._prev_ema50  = ema50
        if ema200 is not None: self._prev_ema200 = ema200
        if psar   is not None: self._prev_psar   = psar
        if stoch_k is not None: self._prev_stoch_k = stoch_k

    # ──────────────────────────────────────────────────────────────────────
    def on_end_of_algorithm(self):
        self.log("=" * 60)
        self.log(f"Final Portfolio Value : ${self.portfolio.total_portfolio_value:,.2f}")
        self.log(f"Total Profit          : ${self.portfolio.total_profit:,.2f}")
        self.log(f"Total Fees            : ${self.portfolio.total_fees:,.2f}")
        self.log("=" * 60)
