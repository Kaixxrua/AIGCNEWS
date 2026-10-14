extends RefCounted
## Hand-inspected source-coordinate polygons; reuse no art and change no UVs.
## Roof planes / round towers are a lighting approximation, not 3D buildings.
const SHADER = preload("res://shaders/meadow_architecture.gdshader")
const FRONT := Vector3(0.24, 0.0, 0.97077)
const SIDE := Vector3(-0.76, 0.0, 0.64992)
const ROOF := Vector3(-0.48, 0.78, 0.4015)
const ROOF_RIGHT := Vector3(0.40, 0.82, 0.408)

static func _face(points: Array, normal: Vector3, kind: float = 0.0) -> Dictionary:
	var polygon := PackedVector2Array()
	for i in range(0, points.size(), 2):
		polygon.append(Vector2(points[i], points[i + 1]))
	return {"polygon": polygon, "normal": normal.normalized(), "kind": kind}

static func city_faces() -> Array[Dictionary]:
	return [
		_face([1324,96,1376,96,1375,192,1322,198], FRONT, 1),
		_face([1318,92,1346,61,1374,92,1374,92], ROOF, 2),
		_face([1174,143,1214,143,1210,223,1170,232], FRONT, 1),
		_face([1170,139,1193,118,1218,139,1218,139], ROOF, 2),
		_face([1263,143,1302,143,1304,197,1261,200], FRONT, 1),
		_face([1273,140,1300,107,1321,140,1321,140], ROOF, 2),
		_face([1439,191,1478,191,1477,267,1437,263], FRONT, 1),
		_face([1443,188,1462,164,1480,188,1480,188], ROOF, 2),
		_face([1397,189,1430,189,1431,254,1395,254], FRONT, 1),
		_face([1408,188,1422,159,1439,188,1439,188], ROOF, 2),
		_face([915,273,963,273,962,359,913,358], FRONT, 1),
		_face([916,269,938,242,960,269,960,269], ROOF, 2),
		_face([823,340,879,340,880,375,823,375], FRONT),
		_face([814,336,854,302,898,336,898,336], ROOF),
		_face([632,400,678,400,679,480,631,480], FRONT, 1),
		_face([628,395,655,357,682,395,682,395], ROOF, 2),
		_face([1090,416,1169,416,1168,449,1090,449], FRONT),
		_face([1079,410,1116,387,1141,387,1175,410], ROOF),
		_face([1203,365,1240,337,1255,359,1290,359], ROOF),
		_face([1234,363,1286,363,1288,399,1234,399], FRONT),
		_face([1284,490,1362,490,1360,518,1284,518], FRONT),
		_face([1274,486,1296,465,1360,465,1370,486], ROOF),
		_face([1467,491,1556,491,1557,551,1467,551], FRONT),
		_face([1460,486,1484,460,1536,460,1561,486], ROOF),
		_face([1652,432,1717,432,1715,464,1652,464], FRONT),
		_face([1632,427,1660,408,1701,408,1721,427], ROOF),
		_face([1093,573,1171,573,1171,600,1093,600], FRONT),
		_face([1079,568,1103,545,1173,545,1188,568], ROOF),
		_face([773,575,843,575,844,622,773,622], FRONT),
		_face([765,570,801,543,821,543,849,570], ROOF_RIGHT),
		_face([299,531,362,531,362,568,299,568], SIDE),
		_face([286,526,336,483,414,526,414,526], ROOF)]

static func village_faces() -> Array[Dictionary]:
	return [
		_face([311,139,443,139,441,251,313,251], FRONT, 1),
		_face([314,134,385,58,444,134,444,134], ROOF, 2),
		_face([1352,190,1443,190,1441,288,1351,288], FRONT, 1),
		_face([1346,184,1392,127,1445,184,1445,184], ROOF, 2),
		_face([163,216,218,161,280,161,250,216], ROOF),
		_face([255,212,277,180,304,214,304,214], ROOF_RIGHT),
		_face([165,221,248,221,246,259,166,259], SIDE),
		_face([68,274,88,231,154,231,180,274], ROOF_RIGHT),
		_face([73,280,116,280,115,325,74,325], FRONT),
		_face([196,304,253,238,322,239,271,304], ROOF),
		_face([275,301,321,247,347,300,347,300], ROOF_RIGHT),
		_face([278,307,340,307,339,368,278,368], FRONT),
		_face([195,309,267,309,267,346,195,346], SIDE),
		_face([447,191,483,122,559,122,512,191], ROOF),
		_face([517,191,560,131,607,191,607,191], ROOF_RIGHT),
		_face([516,197,602,197,602,267,516,267], FRONT),
		_face([675,173,690,118,779,118,790,173], ROOF_RIGHT),
		_face([719,279,747,218,797,218,850,277], ROOF_RIGHT),
		_face([744,284,841,284,841,337,744,337], FRONT),
		_face([570,318,625,276,667,275,634,318], ROOF),
		_face([637,320,668,280,699,320,699,320], ROOF_RIGHT),
		_face([640,326,695,326,695,368,640,368], FRONT),
		_face([827,246,860,183,924,181,884,246], ROOF),
		_face([887,247,927,191,957,247,957,247], ROOF_RIGHT),
		_face([893,253,953,253,953,294,893,294], FRONT),
		_face([901,188,927,129,976,131,1012,191], ROOF_RIGHT),
		_face([1048,271,1073,226,1120,226,1174,274], ROOF_RIGHT),
		_face([1081,281,1169,281,1169,321,1081,321], FRONT),
		_face([1263,321,1293,268,1328,267,1350,319], ROOF),
		_face([1514,292,1545,239,1608,241,1640,293], ROOF),
		_face([1558,300,1647,300,1647,345,1558,345], FRONT),
		_face([1460,211,1482,161,1517,164,1551,211], ROOF_RIGHT)]

static func apply_to(material: ShaderMaterial, label: String, size: Vector2) -> void:
	var faces: Array[Dictionary] = city_faces() if label == "IndependentCastleHill" else village_faces()
	assert(faces.size() <= 32)
	var ab: Array[Vector4] = []
	var cd: Array[Vector4] = []
	var normal_data: Array[Vector4] = []
	for face in faces:
		var points: PackedVector2Array = face.polygon
		var a := points[0] / size
		var b := points[1] / size
		var c := points[2] / size
		var d := points[3] / size
		ab.append(Vector4(a.x, a.y, b.x, b.y))
		cd.append(Vector4(c.x, c.y, d.x, d.y))
		var n: Vector3 = face.normal
		normal_data.append(Vector4(n.x, n.y, n.z, face.kind))
	while ab.size() < 32:
		ab.append(Vector4.ZERO)
		cd.append(Vector4.ZERO)
		normal_data.append(Vector4.ZERO)
	material.shader = SHADER
	material.set_shader_parameter("architecture_count", faces.size())
	material.set_shader_parameter("architecture_ab", ab)
	material.set_shader_parameter("architecture_cd", cd)
	material.set_shader_parameter("architecture_normals", normal_data)
	material.set_shader_parameter("painted_fill", 0.32)
	material.set_shader_parameter("root_contact", 0.20)
	material.set_shader_parameter("art_exposure", 0.94 if label == "IndependentCastleHill" else 0.84)
