extends RefCounted
## Candidate C of four fresh generations. Rectangles are measured source-alpha
## bounds with two transparent pixels of padding, not an assumed equal grid.
const TEXTURE = preload("res://assets/creatures/castle-dragon-turns-v57.png")
const CANVAS := Vector2(300, 292)
const PIVOT := Vector2(150, 178)
const FRAMES: Array[Rect2] = [
	Rect2(23,22,207,227), Rect2(261,24,183,223), Rect2(475,26,196,224), Rect2(683,25,186,225),
	Rect2(913,18,173,239), Rect2(1129,24,185,226), Rect2(1326,26,196,224), Rect2(1554,24,184,223),
	Rect2(9,311,229,133), Rect2(241,311,218,138), Rect2(472,310,199,139), Rect2(677,306,207,147),
	Rect2(888,317,222,142), Rect2(1114,305,207,148), Rect2(1326,310,199,139), Rect2(1538,311,229,138),
	Rect2(23,492,208,163), Rect2(256,506,189,149), Rect2(474,506,179,149), Rect2(667,498,214,157),
	Rect2(899,492,201,162), Rect2(1118,498,213,157), Rect2(1345,506,178,149), Rect2(1552,506,193,149),
	Rect2(20,673,212,183), Rect2(247,679,199,173), Rect2(475,679,195,178), Rect2(683,679,185,177),
	Rect2(908,679,183,192), Rect2(1130,679,185,178), Rect2(1328,679,194,178), Rect2(1551,675,203,178)]
const BODIES: Array[Vector2] = [
	Vector2(126,177), Vector2(352,177), Vector2(581,179), Vector2(792,179),
	Vector2(999,179), Vector2(1217,179), Vector2(1414,179), Vector2(1642,177),
	Vector2(126,374), Vector2(348,377), Vector2(580,376), Vector2(790,377),
	Vector2(999,378), Vector2(1212,377), Vector2(1420,377), Vector2(1640,377),
	Vector2(126,550), Vector2(350,557), Vector2(584,557), Vector2(791,556),
	Vector2(999,551), Vector2(1215,556), Vector2(1425,557), Vector2(1640,557),
	Vector2(126,787), Vector2(350,790), Vector2(580,790), Vector2(790,790),
	Vector2(999,790), Vector2(1218,790), Vector2(1421,790), Vector2(1644,790)]

