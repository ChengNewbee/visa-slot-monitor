import datetime as dt
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VISA_STATE", "/tmp/visa-slot-monitor-test-state.json")

import monitor


def page(card: str) -> str:
    return f'''
    <p class="summary-scope">B1/B2 · 普通面谈 · 五个领馆</p>
    <div class="trend-compare">
      <article class="trend-compare-card trend-compare-card--brief">
        <h3>北京</h3>{card}
      </article>
    </div>
    '''


class MonitorTests(unittest.TestCase):
    def test_parse_full_cn_date(self):
        self.assertEqual(monitor.parse_full_cn_date("2026年10月13日"), dt.date(2026, 10, 13))

    def test_parse_public_summary(self):
        document = page('''
          <p class="summary-date">2026年10月13日</p>
          <p>12 个可约日期（非名额）</p>
          <p class="summary-observed">最近观测：
            <time datetime="2026-09-29T14:16:15.331Z">2026/09/29 22:16</time>（北京时间）
          </p>
        ''')
        result = monitor.parse_public_summary(document)
        self.assertEqual(result["earliest"], dt.date(2026, 10, 13))
        self.assertEqual(result["count"], 12)
        self.assertEqual(result["observed_text"], "2026/09/29 22:16")
        self.assertFalse(result["stale"])

    def test_no_date(self):
        document = page('''
          <p class="summary-date">本次未观测到日期</p>
          <p>0 个可约日期（非名额）</p>
          <time datetime="2026-09-29T14:16:15.331Z">2026/09/29 22:16</time>
        ''')
        result = monitor.parse_public_summary(document)
        self.assertIsNone(result["earliest"])
        self.assertEqual(result["count"], 0)

    def test_stale_is_detected(self):
        document = page('''
          <p class="summary-date">2026年10月13日</p>
          <p>2 个可约日期（非名额）</p>
          <time datetime="2026-09-20T14:16:15.331Z">2026/09/20 22:16</time>
          <p>历史观测，数据已过期，不能据此判断当前可约情况。</p>
        ''')
        self.assertTrue(monitor.parse_public_summary(document)["stale"])


if __name__ == "__main__":
    unittest.main()
