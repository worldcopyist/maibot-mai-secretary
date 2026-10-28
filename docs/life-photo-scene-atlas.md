# Life photo scene atlas / 生活照片场景图集

This atlas groups the built-in simulated-life activities into nine physical locations. Each sheet contains three camera views of **one** place. The supplied living-room picture remains the authoritative original view; `living_room_views.png` extends it. The original wetland picture remains the authoritative park view. New room images use the living room's warm, realistic anime illustration as their style and material reference.

本图集把默认模拟生活活动归入九个地点。每张图横排三个视角，表示**同一地点**，不是三个可任选的房间。用户提供的客厅图是客厅原始视角；公园原图也是公园的原始视角。其他室内图沿用客厅的木色、植物、暖光和插画画风。

| Location / 地点 | Activity examples / 活动 | Reference / 三视角图 | Fixed landmarks / 固定标记 |
| --- | --- | --- | --- |
| Living room / 客厅 | anime, TV, films, sofa rest, books and snacks / 动漫、电视剧、电影、沙发休息、收拾书架 | [living_room_views.png](../assets/life_photo_scenes/living_room_views.png) | Green sofa left, TV right, coffee table center, balcony behind / 左沙发、右电视、中央茶几、后方阳台 |
| Kitchen and dining / 厨房餐桌 | breakfast, lunch, dinner, baking, dishes / 三餐、烤饼干、洗餐具 | [kitchen_dining_views.png](../assets/life_photo_scenes/kitchen_dining_views.png) | Oak lower cabinets, cream uppers, window sink, stove, two-seat table / 木色下柜、奶油色上柜、窗下水槽、灶台、双人桌 |
| Bedroom / 卧室 | making bed, tidying toys, going to sleep / 整理床铺、收玩偶、睡觉 | [bedroom_views.png](../assets/life_photo_scenes/bedroom_views.png) | Bed left, wardrobe right, window behind / 左床、右衣柜、后窗 |
| Hobby desk / 手工桌 | LEGO, fuse beads, drawing, puzzles, photo album, games / 乐高、拼豆、画画、拼图、相册、游戏 | [hobby_desk_views.png](../assets/life_photo_scenes/hobby_desk_views.png) | One wood desk, shelves, craft materials / 固定木桌、置物架、手工材料 |
| Balcony / 阳台植物角 | opening the window, watering plants, enjoying the sunset / 开窗、浇植物、看晚霞 | [balcony_views.png](../assets/life_photo_scenes/balcony_views.png) | Sliding doors, narrow balcony, plant stand, same skyline / 推拉门、窄阳台、花架、同一城市天际线 |
| Bathroom / 洗漱区 | washing up, brushing teeth, bathing / 洗漱、刷牙、洗澡 | [bathroom_views.png](../assets/life_photo_scenes/bathroom_views.png) | Sink and oak vanity left, glass shower right, frosted window / 左洗手台、右淋浴间、磨砂窗 |
| Neighborhood / 附近街道 | short walk, buying dinner ingredients / 附近散步、买晚饭食材 | [neighborhood_views.png](../assets/life_photo_scenes/neighborhood_views.png) | Cream apartment, green-awning grocery, ginkgo, bike rack, crosswalk / 米色公寓、绿篷小店、银杏树、自行车架、斑马线 |
| Fried-chicken restaurant / 炸鸡店 | Thursday's fixed KFC visit / 周四固定 KFC | [fried_chicken_restaurant_views.png](../assets/life_photo_scenes/fried_chicken_restaurant_views.png) | Red-framed entrance, back counter, right red booth, central tables / 红框入口、后柜台、右卡座、中央桌 |
| Wetland park / 湿地公园 | Friday's fixed walk and other park activities / 周五固定散步和公园活动 | [wetland_park_views.png](../assets/life_photo_scenes/wetland_park_views.png) | Lake right, curving path left, wood fence, reeds, large tree, distant hills / 右湖、左小径、木栏、芦苇、大树、远山 |

The first six locations are parts of the same apartment. The hobby desk is a corner of the living space, and the balcony is reached through the living-room sliding doors. For a new view, retain the fixed landmarks and their relative position. Use the current activity to add temporary props only; do not move permanent furniture. For night scenes change the lighting, not the floor plan. Produce a **single image**, never the three-panel reference sheet itself.

前六个地点属于同一套公寓，手工桌在居家活动区，阳台从客厅推拉门进入。新图只随活动改变临时道具和光线，不搬动固定家具。夜间可以开灯，但房间布局保持不变。输出应是**单张场景照**，不能把三格参考图原样当成结果。

The original files remain available as `builtin:home` and `builtin:park`. The nine sheets use `builtin:<filename without .png>`; each location also has a corresponding `*_reference` field in the plugin settings. A custom reference can replace any sheet by placing a PNG/JPEG/WebP file in the installed plugin data directory's `life-photo-references/` and setting that field to its filename. Each file must be at most 8 MB.

原图仍可通过 `builtin:home` 和 `builtin:park` 使用。九张图分别通过 `builtin:文件名去掉.png` 选择，也可以在插件配置里为每个地点填写自制参考图文件名。自制图放在插件数据目录的 `life-photo-references/`，每张不超过 8 MB。

## Generation prompt pattern / 生成提示词格式

The sheets were generated from the original living-room or park image with this pattern, then visually checked. This is a reusable prompt for a new location sheet:

> Create a three-view environment turnaround sheet for ONE fixed location in the same warm realistic anime illustration style as the supplied reference. Treat the reference as the authoritative original view or style reference. Lock these physical landmarks: [list permanent landmarks and their left/right/back positions]. Show three physically possible NEW camera positions: [view A], [view B], [view C]. Keep the same furniture, architectural features, materials, colors and object count across panels. Use one wide triptych with three equal separated panels. No people, animals, text, logos, labels or watermark.

For a generated life photo, use a separate prompt:

> Generate ONE candid smartphone photograph from the bot's own eye level while doing [current activity] at [location]. The bot holds the camera and is invisible in the frame; show what it sees, such as food, a craft project or scenery. Reference image 1, if present, is a three-view sheet of ONE place. Preserve the fixed landmarks, but do not copy its art style or output a triptych, split panel, collage or label. Use the separate `selfie` mode and character reference only for a front-camera selfie. The current MaiBot persona remains authoritative.

## Limits / 使用边界

These are generated reference illustrations, not a measured 3D model. Large landmarks and overall palette were visually checked, but small props, exact counts, door geometry and reverse-view perspective can still drift. The park sheet includes two similar path-side angles. Qwen receives one selected scene sheet for an ordinary first-person photo; a selfie receives the character reference as well. MiniMax ordinary photos use the same location descriptions as text; the sheets do **not** lock MiniMax's geometry. The module is off by default and no paid generation is required to inspect these assets.

这些图不是严格测绘的三维模型。大件布局与色调经过目视检查，细小道具、门窗几何和反向视角仍可能有偏差；公园图有两个相近的岸边视角。千问普通第一人称照片接收一张场景图，自拍才额外接收角色图，最终一致性仍需实际生成验证。MiniMax 普通照片的地点只能靠文字描述，不能保证和这些场景图严格一致。模块默认关闭，查看图集不会触发生图费用。
