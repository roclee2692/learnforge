"""FSRS-4.5 记忆模型（按知识点而不是按卡片）。

同一天对同一知识点的多次作答合并成一次“复习”，评级由当天的得分率决定，
避免一晚上连刷十道题把稳定度吹上天。
"""
from __future__ import annotations

import math

W = [0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031, 1.6474,
     0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755]
DECAY, FACTOR = -0.5, 19 / 81

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4


def retrievability(days: float, stability: float) -> float:
    return (1 + FACTOR * max(days, 0) / stability) ** DECAY


def _d0(g: int) -> float:
    return min(max(W[4] - (g - 3) * W[5], 1), 10)


def init(g: int) -> tuple:
    return W[g - 1], _d0(g)


def review(s: float, d: float, days: float, g: int) -> tuple:
    r = retrievability(days, s)
    if g == AGAIN:
        s2 = W[11] * d ** -W[12] * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
        s2 = min(s2, s)
    else:
        bonus = (W[15] if g == HARD else 1) * (W[16] if g == EASY else 1)
        s2 = s * (1 + math.exp(W[8]) * (11 - d) * s ** -W[9] * (math.exp(W[10] * (1 - r)) - 1) * bonus)
    d2 = d - W[6] * (g - 3)
    d2 = W[7] * _d0(3) + (1 - W[7]) * d2
    return s2, min(max(d2, 1), 10)


def rating(credits: list, confidences: list) -> int:
    """当天的得分率 → 评级。credits 是每次作答的得分（0~1，已扣提示）。"""
    acc = sum(credits) / len(credits)
    if acc < 0.5:
        return AGAIN
    if acc < 0.75:
        return HARD
    if acc >= 0.999 and confidences and min(confidences) >= 0.8:
        return EASY
    return GOOD
