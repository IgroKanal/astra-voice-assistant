extends Node3D

const PROFILES := {
	"female_miku": {
		"name": "Miku", "hair": Color8(76, 43, 126), "accent": Color8(183, 113, 255),
		"eyes": Color8(181, 112, 255), "uniform": Color8(56, 46, 82), "long_hair": true,
		"hair_style": "long_layers", "gender": "female", "shoulder_width": 0.32,
		"torso_width": 0.40, "face_width": 0.42, "eye_scale": 1.08, "skirt": false
	},
	"male_ren": {
		"name": "Ren", "hair": Color8(30, 44, 56), "accent": Color8(56, 226, 237),
		"eyes": Color8(130, 180, 220), "uniform": Color8(39, 54, 78), "long_hair": false,
		"hair_style": "spiky", "gender": "male", "shoulder_width": 0.42,
		"torso_width": 0.51, "face_width": 0.47, "eye_scale": 0.91, "skirt": false
	},
	"female_saya": {
		"name": "Saya", "hair": Color8(202, 199, 216), "accent": Color8(159, 116, 255),
		"eyes": Color8(80, 224, 216), "uniform": Color8(55, 46, 74), "long_hair": false,
		"hair_style": "short_bob", "gender": "female", "shoulder_width": 0.32,
		"torso_width": 0.39, "face_width": 0.42, "eye_scale": 1.08, "skirt": false
	},
	"male_kai": {
		"name": "Kai", "hair": Color8(122, 73, 57), "accent": Color8(174, 103, 255),
		"eyes": Color8(181, 199, 142), "uniform": Color8(39, 35, 47), "long_hair": false,
		"hair_style": "wavy_swept", "gender": "male", "shoulder_width": 0.42,
		"torso_width": 0.50, "face_width": 0.47, "eye_scale": 0.91, "skirt": false
	}
}

const STATE_COLORS := {
	"idle": Color8(90, 106, 140),
	"listening": Color8(54, 214, 235),
	"recognizing": Color8(173, 112, 255),
	"speaking": Color8(124, 242, 192),
	"error": Color8(255, 107, 122)
}

var _avatar_root: Node3D
var _head_root: Node3D
var _mouth_mesh: MeshInstance3D
var _eye_meshes: Array[MeshInstance3D] = []
var _arm_nodes: Array[MeshInstance3D] = []
var _earpiece_material: StandardMaterial3D
var _ring_material: StandardMaterial3D
var _rim_light: OmniLight3D
var _accent_light: OmniLight3D
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
	if _fullscreen_requested():
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
	_connect_state_updates()
	print("ASTRA_AVATAR_READY:" + avatar_id + ":" + _avatar_state)
	print("ASTRA_AVATAR_NAME:" + display_name)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_ESCAPE:
			get_tree().quit()
		elif event.keycode == KEY_F11:
			_toggle_fullscreen()


func _toggle_fullscreen() -> void:
	if DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_FULLSCREEN:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)
	else:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)


func _fullscreen_requested() -> bool:
	for argument in OS.get_cmdline_user_args():
		if argument == "--fullscreen":
			return true
	return false


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
		var arm_swing := sin(_phase * 1.3) * (0.03 if not errored else 0.008)
		for arm in _arm_nodes:
			var side: float = float(arm.get_meta("astra_arm_side"))
			var base_z: float = float(arm.get_meta("astra_arm_base_z"))
			arm.rotation_degrees.z = base_z + side * arm_swing * 57.2958
		var blink_phase := fposmod(_phase, 4.1)
		var blink_weight := clampf(1.0 - abs(blink_phase - 3.94) / 0.12, 0.0, 1.0)
		for eye in _eye_meshes:
			var base_y: float = float(eye.get_meta("astra_eye_base_y"))
			eye.scale.y = base_y * (1.0 - blink_weight * 0.9)
		if _earpiece_material:
			var pulse := 0.5 + 0.5 * sin(_phase * (7.0 if recognizing else 2.2))
			_earpiece_material.emission_energy_multiplier = 1.5 if recognizing else (0.35 + pulse * 0.55 if listening else (0.08 if errored else 0.25))
		var state_color: Color = STATE_COLORS.get(_avatar_state, STATE_COLORS["idle"])
		if _rim_light:
			var rim_pulse := 0.6 + 0.4 * sin(_phase * (6.0 if recognizing else 2.4))
			_rim_light.light_color = state_color
			_rim_light.light_energy = (1.1 + rim_pulse * 0.9) if _avatar_state in ["listening", "speaking", "recognizing"] else (0.35 if errored else 0.55)
		if _ring_material:
			_ring_material.emission = state_color
			_ring_material.emission_energy_multiplier = 1.6 if talking else (1.1 if listening or recognizing else (0.25 if errored else 0.6))


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
	world.glow_enabled = true
	world.glow_intensity = 0.35
	environment.environment = world
	add_child(environment)

	var camera := Camera3D.new()
	camera.name = "PreviewCamera"
	camera.position = Vector3(0.0, 1.75, 6.3)
	camera.fov = 36.0
	camera.current = true
	add_child(camera)
	camera.look_at(Vector3(0.0, 1.5, 0.0), Vector3.UP)

	var key_light := DirectionalLight3D.new()
	key_light.rotation_degrees = Vector3(-27.0, -24.0, 0.0)
	key_light.light_color = Color8(225, 227, 255)
	key_light.light_energy = 1.2
	key_light.shadow_enabled = true
	add_child(key_light)

	_accent_light = OmniLight3D.new()
	_accent_light.name = "CharacterAccentLight"
	_accent_light.position = Vector3(-2.1, 2.7, 2.1)
	_accent_light.light_color = Color8(130, 100, 255)
	_accent_light.light_energy = 0.7
	_accent_light.omni_range = 8.0
	add_child(_accent_light)

	_rim_light = OmniLight3D.new()
	_rim_light.name = "StateRimLight"
	_rim_light.position = Vector3(0.0, 2.4, -2.1)
	_rim_light.light_color = STATE_COLORS["idle"]
	_rim_light.light_energy = 0.55
	_rim_light.omni_range = 7.0
	add_child(_rim_light)

	var floor_mesh := PlaneMesh.new()
	floor_mesh.size = Vector2(12.0, 12.0)
	_add_mesh(self, "Ground", floor_mesh, Vector3(0.0, -0.06, 0.0), Vector3.ONE, _material(Color8(25, 29, 45), 0.25))

	_ring_material = _material(Color8(20, 22, 38), 0.1)
	_ring_material.emission_enabled = true
	_ring_material.emission = STATE_COLORS["idle"]
	_ring_material.emission_energy_multiplier = 0.6
	var ring := TorusMesh.new()
	ring.inner_radius = 0.78
	ring.outer_radius = 0.92
	ring.rings = 48
	ring.ring_segments = 12
	_add_mesh(self, "StateRing", ring, Vector3(0.0, -0.045, 0.0), Vector3.ONE, _ring_material)


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
	var hair_mat := _material(hair, 0.08)
	var dark_hair := _material(hair.darkened(0.22), 0.04)
	var eye_mat := _material(eye_color, 0.08)
	var pupil_mat := _material(Color8(30, 28, 47), 0.0)
	var white := _material(Color8(246, 247, 255), 0.0)
	var cloth := _material(uniform, 0.08)
	var cloth_dark := _material(uniform.darkened(0.28), 0.06)
	var trim := _material(Color8(205, 209, 222), 0.32)
	var accent_mat := _material(accent, 0.15)
	var sole_mat := _material(Color8(17, 19, 29), 0.32)
	cloth.roughness = 0.36
	cloth_dark.roughness = 0.42
	trim.emission_enabled = true
	trim.emission = accent
	trim.emission_energy_multiplier = 0.18
	accent_mat.emission_enabled = true
	accent_mat.emission = accent
	accent_mat.emission_energy_multiplier = 0.85
	_earpiece_material = accent_mat.duplicate() as StandardMaterial3D
	if _accent_light:
		_accent_light.light_color = accent
		_accent_light.light_energy = 0.9

	_head_root = Node3D.new()
	_head_root.name = "HeadRig"
	_head_root.position.y = 2.18
	_head_root.scale = Vector3(0.86, 0.86, 0.86)
	parent.add_child(_head_root)

	_add_tapered(parent, "Uniform", Vector3(0.0, 1.39, 0.0), Vector3(torso_width, 0.78, 0.34), 0.46, 0.58, cloth)
	_add_box(parent, "UnderShirt", Vector3(0.0, 1.40, 0.178), Vector3(torso_width * 0.48, 0.68, 0.035), cloth_dark)
	_add_sphere(parent, "ShoulderLeft", Vector3(-shoulder_width, 1.72, 0.0), Vector3(0.27 if female else 0.32, 0.19, 0.27), cloth)
	_add_sphere(parent, "ShoulderRight", Vector3(shoulder_width, 1.72, 0.0), Vector3(0.27 if female else 0.32, 0.19, 0.27), cloth)
	_add_cylinder(parent, "Neck", Vector3(0.0, 1.94, 0.0), Vector3(0.13 if female else 0.15, 0.28, 0.14), skin)
	_add_cylinder(parent, "RaisedCollar", Vector3(0.0, 1.96, 0.0), Vector3(0.30 if female else 0.34, 0.22, 0.24), cloth)
	_add_box(parent, "CenterPiping", Vector3(0.0, 1.39, 0.202), Vector3(0.024, 0.72, 0.025), trim)
	_add_box(parent, "LapelLeft", Vector3(-0.13, 1.52, 0.204), Vector3(0.045, 0.46, 0.028), trim, Vector3(0.0, 0.0, -17.0))
	_add_box(parent, "LapelRight", Vector3(0.13, 1.52, 0.204), Vector3(0.045, 0.46, 0.028), trim, Vector3(0.0, 0.0, 17.0))
	_add_box(parent, "ChestBadgeBase", Vector3(-0.20 if female else -0.24, 1.60, 0.21), Vector3(0.20, 0.07, 0.035), cloth_dark, Vector3(0.0, 0.0, -10.0))
	_add_box(parent, "ChestBadgeGlow", Vector3(-0.20 if female else -0.24, 1.60, 0.232), Vector3(0.14, 0.028, 0.018), accent_mat, Vector3(0.0, 0.0, -10.0))
	_add_box(parent, "CollarAccentLeft", Vector3(-0.20, 2.00, 0.19), Vector3(0.034, 0.22, 0.024), trim, Vector3(0.0, 0.0, -13.0))
	_add_box(parent, "CollarAccentRight", Vector3(0.20, 2.00, 0.19), Vector3(0.034, 0.22, 0.024), trim, Vector3(0.0, 0.0, 13.0))

	_add_cylinder(parent, "Hips", Vector3(0.0, 0.93, 0.0), Vector3(torso_width * 0.82, 0.25, 0.28), cloth_dark)
	_add_box(parent, "Belt", Vector3(0.0, 1.03, 0.16), Vector3(torso_width * 0.82, 0.055, 0.055), trim)
	_add_box(parent, "BeltBuckle", Vector3(0.0, 1.03, 0.20), Vector3(0.13, 0.10, 0.035), accent_mat)

	for side in [-1.0, 1.0]:
		var upper := _add_tapered(parent, "UpperArm", Vector3(side * (shoulder_width + 0.12), 1.42, 0.0), Vector3(0.12 if female else 0.14, 0.50, 0.13), 0.42, 0.50, cloth)
		upper.rotation_degrees.z = side * 10.0
		upper.set_meta("astra_arm_side", side)
		upper.set_meta("astra_arm_base_z", side * 10.0)
		_arm_nodes.append(upper)
		var forearm := _add_tapered(parent, "Forearm", Vector3(side * (shoulder_width + 0.20), 1.07, 0.015), Vector3(0.095 if female else 0.11, 0.43, 0.105), 0.44, 0.38, cloth_dark)
		forearm.rotation_degrees.z = side * 5.0
		_add_box(parent, "SleeveSeam", Vector3(side * (shoulder_width + 0.23), 1.20, 0.095), Vector3(0.025, 0.35, 0.02), trim, Vector3(0.0, 0.0, side * 6.0))
		_add_cylinder(parent, "Cuff", Vector3(side * (shoulder_width + 0.23), 0.83, 0.025), Vector3(0.11 if female else 0.13, 0.075, 0.12), trim)
		_add_box(parent, "CuffGlow", Vector3(side * (shoulder_width + 0.23), 0.83, 0.105), Vector3(0.095, 0.025, 0.018), accent_mat)
		_add_sphere(parent, "Palm", Vector3(side * (shoulder_width + 0.24), 0.72, 0.035), Vector3(0.085, 0.13, 0.075), skin)
		for finger in range(3):
			_add_box(parent, "Finger", Vector3(side * (shoulder_width + 0.21 + float(finger) * 0.028), 0.57, 0.055), Vector3(0.023, 0.15, 0.025), skin, Vector3(0.0, 0.0, side * (finger - 1) * 3.0))

		_add_tapered(parent, "Thigh", Vector3(side * 0.12, 0.66, 0.0), Vector3(0.14 if female else 0.16, 0.52, 0.15), 0.46, 0.40, cloth_dark)
		_add_tapered(parent, "Shin", Vector3(side * 0.13, 0.29, 0.0), Vector3(0.105 if female else 0.12, 0.40, 0.12), 0.42, 0.36, cloth_dark)
		_add_box(parent, "KneeGlow", Vector3(side * 0.13, 0.47, 0.09), Vector3(0.025, 0.12, 0.02), accent_mat, Vector3(0.0, 0.0, side * 22.0))
		_add_box(parent, "BootShaft", Vector3(side * 0.14, 0.12, 0.0), Vector3(0.15 if female else 0.17, 0.22, 0.16), sole_mat)
		_add_box(parent, "BootToe", Vector3(side * 0.14, 0.035, 0.12), Vector3(0.16 if female else 0.18, 0.09, 0.20), sole_mat)
		_add_box(parent, "BootSole", Vector3(side * 0.14, -0.015, 0.09), Vector3(0.18 if female else 0.20, 0.035, 0.29), sole_mat)
		_add_box(parent, "BootGlow", Vector3(side * 0.14, 0.13, 0.09), Vector3(0.09, 0.10, 0.02), accent_mat)

	if female:
		for side in [-1.0, 1.0]:
			_add_box(parent, "JacketPanel", Vector3(side * 0.13, 0.81, 0.12), Vector3(0.22, 0.42, 0.06), cloth, Vector3(0.0, 0.0, side * 7.0))
			_add_box(parent, "JacketEdge", Vector3(side * 0.24, 0.81, 0.155), Vector3(0.035, 0.43, 0.025), trim, Vector3(0.0, 0.0, side * 7.0))
	else:
		for side in [-1.0, 1.0]:
			_add_box(parent, "CoatPanel", Vector3(side * 0.15, 0.67, 0.05), Vector3(0.27, 0.64, 0.065), cloth, Vector3(0.0, 0.0, side * 6.0))
			_add_box(parent, "CoatEdge", Vector3(side * 0.27, 0.67, 0.105), Vector3(0.035, 0.64, 0.025), trim, Vector3(0.0, 0.0, side * 6.0))
			_add_box(parent, "CoatGlow", Vector3(side * 0.15, 0.48, 0.095), Vector3(0.035, 0.30, 0.02), accent_mat, Vector3(0.0, 0.0, side * 6.0))

	_add_sphere(_head_root, "Face", Vector3(0.0, 0.32, 0.0), Vector3(face_width, 0.61 if female else 0.58, 0.39), skin)
	_add_sphere(_head_root, "EarLeft", Vector3(-0.45, 0.34, 0.0), Vector3(0.1, 0.15, 0.11), skin)
	_add_sphere(_head_root, "EarRight", Vector3(0.45, 0.34, 0.0), Vector3(0.1, 0.15, 0.11), skin)
	_add_sphere(_head_root, "AssistantEarpiece", Vector3(0.49, 0.30, 0.08), Vector3(0.08, 0.18, 0.1), dark_hair)
	_add_box(_head_root, "EarpieceLight", Vector3(0.53, 0.30, 0.164), Vector3(0.025, 0.095, 0.015), _earpiece_material)

	_add_sphere(_head_root, "HairCrown", Vector3(0.0, 0.70, 0.015), Vector3(0.51, 0.34, 0.43), hair_mat)
	var side_length := 0.68 if profile["long_hair"] else 0.36
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
	_build_hair_style(_head_root, String(profile["hair_style"]), hair_mat, dark_hair, accent_mat)


func _build_hair_style(parent: Node3D, style: String, hair: Material, dark: Material, accent: Material) -> void:
	match style:
		"long_layers":
			_add_sphere(parent, "BackHair", Vector3(0.0, -0.10, -0.25), Vector3(0.43, 0.94, 0.20), dark)
			for long_side in [-1.0, 1.0]:
				_add_sphere(parent, "LongLayer", Vector3(long_side * 0.43, 0.02, -0.08), Vector3(0.20, 0.82, 0.22), hair, Vector3(0.0, 0.0, long_side * -7.0))
				_add_sphere(parent, "LayerTip", Vector3(long_side * 0.48, -0.45, -0.02), Vector3(0.13, 0.32, 0.16), dark, Vector3(0.0, 0.0, long_side * -12.0))
				var front_strand := _add_tapered(parent, "FrontStrand", Vector3(long_side * 0.28, 0.30, 0.30), Vector3(0.075, 0.62, 0.055), 0.40, 0.20, hair)
				front_strand.rotation_degrees.z = long_side * 7.0
				_add_sphere(parent, "HairGlint", Vector3(long_side * 0.47, 0.10, 0.07), Vector3(0.025, 0.48, 0.018), accent, Vector3(0.0, 0.0, long_side * -7.0))
		"short_bob":
			_add_sphere(parent, "BobBack", Vector3(0.0, 0.26, -0.24), Vector3(0.50, 0.48, 0.22), hair)
			for bob_side in [-1.0, 1.0]:
				_add_sphere(parent, "BobLock", Vector3(bob_side * 0.42, 0.28, 0.08), Vector3(0.16, 0.38, 0.19), hair, Vector3(0.0, 0.0, bob_side * 10.0))
				_add_sphere(parent, "BobTip", Vector3(bob_side * 0.38, 0.02, 0.12), Vector3(0.10, 0.13, 0.13), dark, Vector3(0.0, 0.0, bob_side * 18.0))
			_add_sphere(parent, "AccentStreak", Vector3(0.18, 0.72, 0.24), Vector3(0.055, 0.27, 0.035), accent, Vector3(0.0, 0.0, -18.0))
		"spiky":
			for spike_index in range(7):
				var spike_x := -0.39 + float(spike_index) * 0.13
				var spike := _add_cone(parent, "HairSpike", Vector3(spike_x, 0.82 + abs(3.0 - float(spike_index)) * -0.015, 0.02), Vector3(0.11, 0.34, 0.11), hair, Vector3(0.0, 0.0, (3.0 - float(spike_index)) * 7.0))
				spike.rotation_degrees.x = -4.0 + float(spike_index) * 1.2
			for spiky_side in [-1.0, 1.0]:
				_add_sphere(parent, "SpikySide", Vector3(spiky_side * 0.39, 0.44, 0.02), Vector3(0.15, 0.30, 0.17), hair, Vector3(0.0, 0.0, spiky_side * 15.0))
				_add_sphere(parent, "SpikyTip", Vector3(spiky_side * 0.45, 0.28, 0.10), Vector3(0.08, 0.16, 0.10), dark, Vector3(0.0, 0.0, spiky_side * 20.0))
		"wavy_swept":
			_add_sphere(parent, "WavyCrown", Vector3(0.0, 0.76, 0.06), Vector3(0.38, 0.20, 0.30), hair)
			_add_sphere(parent, "SideSweep", Vector3(-0.17, 0.74, 0.20), Vector3(0.27, 0.18, 0.20), hair, Vector3(0.0, 0.0, -23.0))
			_add_sphere(parent, "SideSweepTip", Vector3(-0.31, 0.57, 0.24), Vector3(0.10, 0.19, 0.12), dark, Vector3(0.0, 0.0, -25.0))
			for wave_index in range(4):
				var wave_side := -1.0 if wave_index % 2 == 0 else 1.0
				var wave_x := -0.34 + float(wave_index) * 0.22
				_add_sphere(parent, "WaveTip", Vector3(wave_x, 0.55 + float(wave_index) * 0.035, 0.28), Vector3(0.11, 0.15, 0.11), dark if wave_index % 2 == 0 else hair, Vector3(0.0, 0.0, wave_side * 18.0))


func _build_overlay(display_name: String) -> void:
	var layer := CanvasLayer.new()
	var label := Label.new()
	var state_label: String = {
		"idle": "ГОТОВА", "listening": "СЛУШАЕТ", "recognizing": "ДУМАЕТ",
		"speaking": "ГОВОРИТ", "error": "ОШИБКА"
	}.get(_avatar_state, "ГОТОВА")
	label.text = "3D AVATAR  ·  " + display_name + "  ·  " + state_label + "  ·  F11 — полный экран, Esc — выход"
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


func _add_tapered(parent: Node3D, name: String, position: Vector3, scale: Vector3, top_radius: float, bottom_radius: float, material: Material) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.top_radius = top_radius
	mesh.bottom_radius = bottom_radius
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
