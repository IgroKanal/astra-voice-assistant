extends Node3D

const PROFILES := {
	"female_miku": {
		"name": "Miku", "hair": Color8(54, 37, 111), "accent": Color8(173, 112, 255),
		"eyes": Color8(177, 128, 255), "uniform": Color8(35, 34, 67), "long_hair": true,
		"hair_style": "twin_tails", "gender": "female", "shoulder_width": 0.34,
		"torso_width": 0.43, "face_width": 0.43, "eye_scale": 1.08
	},
	"male_ren": {
		"name": "Ren", "hair": Color8(35, 44, 59), "accent": Color8(54, 214, 235),
		"eyes": Color8(155, 200, 235), "uniform": Color8(29, 38, 58), "long_hair": false,
		"hair_style": "spiky", "gender": "male", "shoulder_width": 0.42,
		"torso_width": 0.51, "face_width": 0.47, "eye_scale": 0.91
	},
	"female_saya": {
		"name": "Saya", "hair": Color8(194, 194, 219), "accent": Color8(164, 116, 255),
		"eyes": Color8(80, 224, 216), "uniform": Color8(35, 34, 67), "long_hair": true,
		"hair_style": "side_ponytail", "gender": "female", "shoulder_width": 0.34,
		"torso_width": 0.43, "face_width": 0.43, "eye_scale": 1.08
	},
	"male_kai": {
		"name": "Kai", "hair": Color8(102, 61, 48), "accent": Color8(173, 112, 255),
		"eyes": Color8(181, 199, 142), "uniform": Color8(39, 34, 57), "long_hair": false,
		"hair_style": "swept", "gender": "male", "shoulder_width": 0.42,
		"torso_width": 0.51, "face_width": 0.47, "eye_scale": 0.91
	}
}

var _avatar_root: Node3D
var _head_root: Node3D
var _mouth_mesh: MeshInstance3D
var _eye_meshes: Array[MeshInstance3D] = []
var _earpiece_material: StandardMaterial3D
var _avatar_state := "idle"
var _phase := 0.0
var _state_peer: StreamPeerTCP
var _state_token := ""
var _state_token_sent := false
var _state_buffer := ""


func _ready() -> void:
	var avatar_id := _selected_avatar()
	_avatar_state = _selected_state()
	_build_stage()
	_avatar_root = Node3D.new()
	_avatar_root.name = "OriginalProceduralAvatar"
	add_child(_avatar_root)
	_build_character(_avatar_root, PROFILES[avatar_id])
	var default_name: String = String(PROFILES[avatar_id]["name"])
	var display_name: String = _selected_name(default_name)
	_build_overlay(display_name)
	_connect_state_updates()
	print("ASTRA_AVATAR_READY:" + avatar_id + ":" + _avatar_state)
	print("ASTRA_AVATAR_NAME:" + display_name)


func _process(delta: float) -> void:
	_poll_state_updates()
	_phase += delta
	if _avatar_root:
		var talking := _avatar_state == "speaking"
		var listening := _avatar_state == "listening"
		var recognizing := _avatar_state == "recognizing"
		var errored := _avatar_state == "error"
		_avatar_root.position.y = sin(_phase * 1.3) * (0.025 if not errored else 0.008)
		_avatar_root.rotation.y = sin(_phase * 0.55) * (0.045 if not errored else 0.012)
		if _head_root:
			_head_root.rotation.z = sin(_phase * 0.8) * (0.035 if listening else 0.012)
			_head_root.rotation.x = -0.09 if errored else (sin(_phase * 2.2) * 0.012 if recognizing else 0.0)
		if _mouth_mesh:
			_mouth_mesh.scale.y = 0.12 + abs(sin(_phase * 12.0)) * 0.58 if talking else 0.12
		var blink_phase := fposmod(_phase, 4.1)
		var blink_weight := clampf(1.0 - abs(blink_phase - 3.94) / 0.12, 0.0, 1.0)
		for eye in _eye_meshes:
			var base_y: float = float(eye.get_meta("astra_eye_base_y"))
			eye.scale.y = base_y * (1.0 - blink_weight * 0.9)
		if _earpiece_material:
			var pulse := 0.5 + 0.5 * sin(_phase * (7.0 if recognizing else 2.2))
			_earpiece_material.emission_energy_multiplier = 1.5 if recognizing else (0.35 + pulse * 0.55 if listening else (0.08 if errored else 0.25))


func _selected_avatar() -> String:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--avatar="):
			var candidate := argument.trim_prefix("--avatar=")
			if PROFILES.has(candidate):
				return candidate
	return "female_saya"


func _selected_state() -> String:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--state="):
			var candidate := argument.trim_prefix("--state=")
			if candidate in ["idle", "listening", "recognizing", "speaking", "error"]:
				return candidate
	return "idle"


func _selected_name(default_name: String) -> String:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--name="):
			var candidate: String = argument.trim_prefix("--name=").strip_edges()
			if candidate.length() >= 1 and candidate.length() <= 32 and candidate.find("\n") == -1 and candidate.find("\r") == -1:
				return candidate
	return default_name


func _connect_state_updates() -> void:
	var port: int = -1
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--port="):
			port = argument.trim_prefix("--port=").to_int()
		elif argument.begins_with("--token="):
			_state_token = argument.trim_prefix("--token=")
	if port < 1 or port > 65535 or _state_token.length() != 64:
		return
	for character in _state_token:
		if not character in "0123456789abcdef":
			_state_token = ""
			return
	_state_peer = StreamPeerTCP.new()
	_state_peer.connect_to_host("127.0.0.1", port)


func _poll_state_updates() -> void:
	if _state_peer == null:
		return
	_state_peer.poll()
	if _state_peer.get_status() == StreamPeerTCP.STATUS_CONNECTED and not _state_token_sent:
		_state_peer.put_data((_state_token + "\n").to_utf8_buffer())
		_state_token_sent = true
	if _state_peer.get_status() == StreamPeerTCP.STATUS_ERROR:
		_state_peer = null
		return
	var available: int = _state_peer.get_available_bytes()
	if available <= 0:
		return
	if available > 1024:
		_state_peer = null
		return
	_state_buffer += _state_peer.get_utf8_string(available)
	if _state_buffer.length() > 512:
		_state_peer = null
		return
	while _state_buffer.contains("\n"):
		var line: String = _state_buffer.substr(0, _state_buffer.find("\n")).strip_edges()
		_state_buffer = _state_buffer.substr(_state_buffer.find("\n") + 1)
		if line == "CLOSE":
			get_tree().quit()
			return
		if line.begins_with("STATE:"):
			var state: String = line.trim_prefix("STATE:")
			if state in ["idle", "listening", "recognizing", "speaking", "error"]:
				if _avatar_state != state:
					_avatar_state = state
					print("ASTRA_AVATAR_STATE:" + state)


func _build_stage() -> void:
	var environment := WorldEnvironment.new()
	var world := Environment.new()
	world.background_mode = Environment.BG_COLOR
	world.background_color = Color8(16, 19, 30)
	environment.environment = world
	add_child(environment)

	var camera := Camera3D.new()
	camera.name = "PreviewCamera"
	camera.position = Vector3(0.0, 1.65, 5.4)
	camera.fov = 34.0
	camera.current = true
	add_child(camera)
	camera.look_at(Vector3(0.0, 1.55, 0.0), Vector3.UP)

	var key_light := DirectionalLight3D.new()
	key_light.rotation_degrees = Vector3(-27.0, -24.0, 0.0)
	key_light.light_color = Color8(225, 227, 255)
	key_light.light_energy = 1.2
	key_light.shadow_enabled = true
	add_child(key_light)

	var fill_light := OmniLight3D.new()
	fill_light.position = Vector3(-2.0, 2.5, 2.0)
	fill_light.light_color = Color8(130, 100, 255)
	fill_light.light_energy = 0.7
	fill_light.omni_range = 8.0
	add_child(fill_light)

	var floor_mesh := PlaneMesh.new()
	floor_mesh.size = Vector2(12.0, 12.0)
	_add_mesh(self, "Ground", floor_mesh, Vector3(0.0, -0.06, 0.0), Vector3.ONE, _material(Color8(25, 29, 45), 0.25))


func _build_character(parent: Node3D, profile: Dictionary) -> void:
	var hair: Color = profile["hair"]
	var accent: Color = profile["accent"]
	var uniform: Color = profile["uniform"]
	var female := String(profile["gender"]) == "female"
	var shoulder_width: float = float(profile["shoulder_width"])
	var torso_width: float = float(profile["torso_width"])
	var face_width: float = float(profile["face_width"])
	var eye_scale: float = float(profile["eye_scale"])
	var eye_color: Color = profile["eyes"]
	var skin := _material(Color8(255, 218, 202), 0.0)
	var hair_mat := _material(hair, 0.05)
	var dark_hair := _material(hair.darkened(0.2), 0.02)
	var eye_mat := _material(eye_color, 0.05)
	var pupil_mat := _material(Color8(30, 28, 47), 0.0)
	var white := _material(Color8(246, 247, 255), 0.0)
	var cloth := _material(uniform, 0.12)
	var trim := _material(accent, 0.25)
	_earpiece_material = trim.duplicate() as StandardMaterial3D
	_earpiece_material.emission_enabled = true
	_earpiece_material.emission = accent
	_earpiece_material.emission_energy_multiplier = 0.25
	_head_root = Node3D.new()
	_head_root.name = "HeadRig"
	_head_root.position.y = 1.65
	parent.add_child(_head_root)

	# Upper body, raised collar, and luminous uniform piping.
	_add_cylinder(parent, "Uniform", Vector3(0.0, 0.78, 0.0), Vector3(torso_width, 0.76, 0.31), cloth)
	_add_sphere(parent, "ShoulderLeft", Vector3(-shoulder_width, 1.12, 0.0), Vector3(0.29 if female else 0.34, 0.21, 0.29), cloth)
	_add_sphere(parent, "ShoulderRight", Vector3(shoulder_width, 1.12, 0.0), Vector3(0.29 if female else 0.34, 0.21, 0.29), cloth)
	_add_cylinder(parent, "Neck", Vector3(0.0, 1.42, 0.0), Vector3(0.13 if female else 0.15, 0.3, 0.14), skin)
	_add_cylinder(parent, "RaisedCollar", Vector3(0.0, 1.39, 0.0), Vector3(0.30 if female else 0.34, 0.2, 0.25), cloth)
	_add_box(parent, "CenterPiping", Vector3(0.0, 0.78, 0.315), Vector3(0.025, 0.72, 0.025), trim)
	_add_box(parent, "ChestAccent", Vector3(0.22, 0.98, 0.295), Vector3(0.17, 0.035, 0.025), trim)
	_add_box(parent, "CollarAccentLeft", Vector3(-0.22, 1.43, 0.22), Vector3(0.035, 0.23, 0.025), trim, Vector3(0.0, 0.0, -12.0))
	_add_box(parent, "CollarAccentRight", Vector3(0.22, 1.43, 0.22), Vector3(0.035, 0.23, 0.025), trim, Vector3(0.0, 0.0, 12.0))

	# Soft anime-style face volume and ear-mounted assistant indicator.
	_add_sphere(_head_root, "Face", Vector3(0.0, 0.32, 0.0), Vector3(face_width, 0.61 if female else 0.58, 0.39), skin)
	_add_sphere(_head_root, "EarLeft", Vector3(-0.45, 0.34, 0.0), Vector3(0.1, 0.15, 0.11), skin)
	_add_sphere(_head_root, "EarRight", Vector3(0.45, 0.34, 0.0), Vector3(0.1, 0.15, 0.11), skin)
	_add_sphere(_head_root, "AssistantEarpiece", Vector3(0.49, 0.30, 0.08), Vector3(0.08, 0.18, 0.1), dark_hair)
	_add_box(_head_root, "EarpieceLight", Vector3(0.53, 0.30, 0.164), Vector3(0.025, 0.095, 0.015), _earpiece_material)

	# Layered crown, side locks, and bangs give the blockout an anime silhouette.
	_add_sphere(_head_root, "HairCrown", Vector3(0.0, 0.70, 0.015), Vector3(0.51, 0.34, 0.43), hair_mat)
	var side_length := 0.66 if profile["long_hair"] else 0.36
	for side in [-1.0, 1.0]:
		_add_sphere(_head_root, "SideLock", Vector3(side * 0.39, 0.43, 0.0), Vector3(0.19, side_length, 0.22), hair_mat)
		_eye_meshes.append(_add_sphere(_head_root, "EyeWhite", Vector3(side * 0.18, 0.37, 0.35), Vector3(0.115, 0.078 * eye_scale, 0.052), white))
		_eye_meshes.append(_add_sphere(_head_root, "Iris", Vector3(side * 0.18, 0.365, 0.396), Vector3(0.056, 0.06 * eye_scale, 0.025), eye_mat))
		_eye_meshes.append(_add_sphere(_head_root, "Pupil", Vector3(side * 0.18, 0.362, 0.418), Vector3(0.026, 0.04 * eye_scale, 0.015), pupil_mat))
		_eye_meshes.append(_add_sphere(_head_root, "EyeHighlight", Vector3(side * 0.195, 0.39, 0.43), Vector3(0.018, 0.018, 0.01), white))
		_add_sphere(_head_root, "Brow", Vector3(side * 0.18, 0.48, 0.36), Vector3(0.12, 0.025, 0.028), dark_hair, Vector3(0.0, 0.0, -side * 8.0))
		_add_sphere(_head_root, "Bang", Vector3(side * 0.16, 0.60, 0.31), Vector3(0.14, 0.29, 0.11), hair_mat, Vector3(0.0, 0.0, side * 24.0))
	_add_sphere(_head_root, "CenterBang", Vector3(0.0, 0.56, 0.35), Vector3(0.12, 0.31, 0.1), dark_hair, Vector3(0.0, 0.0, -4.0))
	_add_sphere(_head_root, "Nose", Vector3(0.0, 0.22, 0.386), Vector3(0.035, 0.05, 0.028), _material(Color8(255, 197, 183), 0.0))
	_mouth_mesh = _add_sphere(_head_root, "Mouth", Vector3(0.0, 0.07, 0.383), Vector3(0.07, 0.018, 0.02), _material(Color8(145, 75, 95), 0.0))
	_build_hair_style(_head_root, String(profile["hair_style"]), hair_mat, dark_hair, trim)


func _build_hair_style(parent: Node3D, style: String, hair: Material, dark: Material, accent: Material) -> void:
	match style:
		"twin_tails":
			for side in [-1.0, 1.0]:
				_add_sphere(parent, "TwinTail", Vector3(side * 0.54, 0.22, -0.02), Vector3(0.22, 0.68, 0.24), hair, Vector3(0.0, 0.0, side * -18.0))
				_add_sphere(parent, "TailTie", Vector3(side * 0.52, 0.48, 0.02), Vector3(0.14, 0.09, 0.15), accent)
		"side_ponytail":
			_add_sphere(parent, "SidePonytail", Vector3(0.51, 0.12, -0.04), Vector3(0.23, 0.72, 0.26), hair, Vector3(0.0, 0.0, -18.0))
			_add_sphere(parent, "PonytailTie", Vector3(0.47, 0.48, 0.02), Vector3(0.16, 0.08, 0.16), accent)
		"spiky":
			for index in range(5):
				var x := -0.34 + float(index) * 0.17
				_add_cone(parent, "HairSpike", Vector3(x, 0.82, 0.02), Vector3(0.12, 0.32, 0.12), hair, Vector3(0.0, 0.0, (2.0 - float(index)) * 8.0))
		"swept":
			_add_sphere(parent, "SideSweep", Vector3(-0.17, 0.76, 0.18), Vector3(0.26, 0.17, 0.21), hair, Vector3(0.0, 0.0, -22.0))
			_add_sphere(parent, "SideSweepTip", Vector3(-0.30, 0.59, 0.22), Vector3(0.10, 0.18, 0.12), dark, Vector3(0.0, 0.0, -24.0))


func _build_overlay(display_name: String) -> void:
	var layer := CanvasLayer.new()
	var label := Label.new()
	var state_label: String = {
		"idle": "ГОТОВА", "listening": "СЛУШАЕТ", "recognizing": "ДУМАЕТ",
		"speaking": "ГОВОРИТ", "error": "ОШИБКА"
	}.get(_avatar_state, "ГОТОВА")
	label.text = "3D AVATAR PROTOTYPE  ·  " + display_name + "  ·  " + state_label
	label.position = Vector2(18.0, 16.0)
	label.add_theme_color_override("font_color", Color8(221, 221, 255))
	label.add_theme_font_size_override("font_size", 15)
	layer.add_child(label)
	add_child(layer)


func _material(color: Color, metalness: float) -> StandardMaterial3D:
	var result := StandardMaterial3D.new()
	result.albedo_color = color
	result.metallic = metalness
	result.roughness = 0.48
	return result


func _add_sphere(parent: Node3D, name: String, position: Vector3, scale: Vector3, material: Material, rotation: Vector3 = Vector3.ZERO) -> MeshInstance3D:
	var mesh := SphereMesh.new()
	mesh.radius = 1.0
	mesh.height = 2.0
	mesh.radial_segments = 24
	mesh.rings = 16
	return _add_mesh(parent, name, mesh, position, scale, material, rotation)


func _add_cylinder(parent: Node3D, name: String, position: Vector3, scale: Vector3, material: Material) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.top_radius = 0.5
	mesh.bottom_radius = 0.5
	mesh.height = 1.0
	mesh.radial_segments = 24
	return _add_mesh(parent, name, mesh, position, scale, material)


func _add_cone(parent: Node3D, name: String, position: Vector3, scale: Vector3, material: Material, rotation: Vector3 = Vector3.ZERO) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.top_radius = 0.0
	mesh.bottom_radius = 0.5
	mesh.height = 1.0
	mesh.radial_segments = 12
	return _add_mesh(parent, name, mesh, position, scale, material, rotation)


func _add_box(parent: Node3D, name: String, position: Vector3, size: Vector3, material: Material, rotation: Vector3 = Vector3.ZERO) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = Vector3.ONE
	return _add_mesh(parent, name, mesh, position, size, material, rotation)


func _add_mesh(parent: Node3D, name: String, mesh: Mesh, position: Vector3, scale: Vector3, material: Material, rotation: Vector3 = Vector3.ZERO) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = name
	instance.mesh = mesh
	instance.position = position
	instance.scale = scale
	if name in ["EyeWhite", "Iris", "Pupil", "EyeHighlight"]:
		instance.set_meta("astra_eye_base_y", scale.y)
	instance.rotation_degrees = rotation
	instance.material_override = material
	parent.add_child(instance)
	return instance
