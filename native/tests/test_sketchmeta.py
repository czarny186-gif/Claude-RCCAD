import math, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from rccad import sketchmeta as m


class SketchMetaTests(unittest.TestCase):
    def test_values_roundtrip_all_shapes(self):
        metas = [dict(tool='rect', points=[[0, 0], [20, 10]]), dict(tool='polygon', points=[[0, 0], [5, 0]], sides=5),
                 dict(tool='arc', points=[[0, 0], [5, 3], [10, 0]]), dict(tool='rect3', points=[[0, 0], [10, 0], [3, 4]]),
                 dict(tool='slot', points=[[0, 0], [10, 0], [2, 2]]), dict(tool='circle3', points=[[5, 0], [0, 5], [-5, 0]]),
                 dict(tool='text', points=[[0, 0]], size=10, angle=0)]
        for meta in metas:
            v = [float(x) for x in m.values(meta)]
            again = m.values(m.apply_values(meta, v))
            self.assertEqual([round(float(x), 3) for x in again], [round(x, 3) for x in v], meta['tool'])
            doubled = m.values(m.apply_values(meta, [v[0] * 2, *v[1:]]))
            self.assertAlmostEqual(float(doubled[0]), v[0] * 2, 2, meta['tool'])

    def test_arc_apex_and_height(self):
        self.assertAlmostEqual(m.arc_apex((0, 0), (5, 3), (10, 0))[1], 3, 6)
        self.assertAlmostEqual(m.arc_apex((0, 0), (5, -3), (10, 0))[1], -3, 6)

    def test_drag_grips(self):
        r = m.grab_apply(dict(tool='rect', points=[[0, 0], [20, 10]]), m.grab_info('rect', [(0, 0), (20, 10)], (20, 5), 1.0), (30, 5))
        self.assertEqual(r['points'], [[0, 0], [30, 10]])
        s = m.grab_apply(dict(tool='slot', points=[[0, 0], [10, 0], [2, 2]]), 2, (5, 3))
        self.assertEqual(m.values(s), ['10.0', '6.0'])
        c = m.grab_apply(dict(tool='circle3', points=[[5, 0], [0, 5], [-5, 0]]), 1, (0, 7))
        self.assertEqual(c['points'][1], [0, 7])

    def test_text_box_and_drag(self):
        box = m.text_box([(0, 0), (10, 0), (10, 4), (0, 4)], (0, 0), 0)
        self.assertEqual([round(x, 3) for x in box['move']], [5.0, 2.0])
        meta = dict(tool='text', points=[[1, 1]], size=10, angle=0)
        self.assertEqual(m.text_drag(meta, 'move', (0, 0), (3, 2))['points'], [[4, 3]])
        self.assertAlmostEqual(m.text_drag(meta, 'scale', (5, 1), (10, 1))['size'], 22.5, 6)
        self.assertAlmostEqual(m.text_drag(meta, 'rotate', (2, 1), (1, 2))['angle'], 90, 6)


if __name__ == '__main__':
    unittest.main()
