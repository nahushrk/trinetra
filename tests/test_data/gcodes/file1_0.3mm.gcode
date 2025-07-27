;FLAVOR:Marlin
M73 P0
M117 Time Left 3h59m15s
;TIME:14355
;Filament used: 8.1343m
;Layer height: 0.3
;MINX:70.7
;MINY:41.801
;MINZ:0.2
;MAXX:149.298
;MAXY:179.397
;MAXZ:71.8
;TARGET_MACHINE.NAME:Creality Ender-3 Pro
;POSTPROCESSED
;Generated with Cura_SteamEngine 5.5.0
;

M140 S70
M105
M190 S70
M104 S220
M105
M109 S220
M82 ;absolute extrusion mode

G28 ;Home

;...

M84 X Y E ;Disable all steppers but Z
M82 ;absolute extrusion mode
M104 S0
;End of Gcode
;SETTING_3 {"global_quality": "[general]\\nversion = 4\\nname = klipper-0.3-100m
;SETTING_3 ms\\ndefinition = creality_ender3pro\\n\\n[metadata]\\ntype = quality
;SETTING_3 _changes\\nquality_type = standard\\nsetting_version = 22\\n\\n[value
;SETTING_3 s]\\nacceleration_enabled = False\\nadhesion_type = brim\\nlayer_heig
;SETTING_3 ht = 0.2\\nsupport_enable = True\\nsupport_structure = tree\\nsupport
;SETTING_3 _type = everywhere\\n\\n", "extruder_quality": ["[general]\\nversion 
;SETTING_3 = 4\\nname = klipper-0.3-100mms\\ndefinition = creality_ender3pro\\n\
;SETTING_3 \n[metadata]\\ntype = quality_changes\\nquality_type = standard\\nint
;SETTING_3 ent_category = default\\nposition = 0\\nsetting_version = 22\\n\\n[va
;SETTING_3 lues]\\nbrim_line_count = 10\\ngradual_infill_steps = 0\\ninfill_patt
;SETTING_3 ern = lines\\ninfill_sparse_density = 25.0\\ninitial_layer_line_width
;SETTING_3 _factor = 110.0\\nmeshfix_union_all = False\\nmeshfix_union_all_remov
;SETTING_3 e_holes = False\\nminimum_support_area = 0.0\\nretraction_amount = 0.
;SETTING_3 8\\nretraction_extrusion_window = 2.0\\nretraction_hop = 0.2\\nretrac
;SETTING_3 tion_hop_enabled = True\\nretraction_speed = 40\\nspeed_print = 100.0
;SETTING_3 \\nspeed_support_bottom = 50.0\\nspeed_travel = 100.0\\nspeed_travel_
;SETTING_3 layer_0 = 50.0\\nspeed_wall = 100.0\\nsupport_angle = 75.0\\nsupport_
;SETTING_3 interface_enable = True\\nsupport_pattern = grid\\nsupport_tree_angle
;SETTING_3  = 65.0\\n\\n"]}
