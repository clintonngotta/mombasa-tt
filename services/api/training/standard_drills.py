# ruff: noqa: E501  (drill prose reads better unwrapped)
"""The standard drill library every player sees (REQ-026). Loaded by migration 0003 under fixed ids, so a
later change to this list needs a new migration that loads it again.

Patterns are for a right-handed player ("you", at the near end): "right" is your forehand side, "left"
your backhand side. Your partner, facing you, has their forehand on your left. Each step is a ball landing:
"partner" steps land on your side and are labelled with the stroke you play from there ("BH", "FH pivot",
"FH wide"); "you" steps land on your partner's side, labelled with what they play. See Drill.pattern.

Video links are YouTube searches, not chosen videos: nobody has checked a particular video for each drill.
Coaches can put a specific video on their club's own copy."""


def step(hitter, stroke, x, depth, note=""):
    made = {"hitter": hitter, "stroke": stroke, "x": x, "depth": depth}
    return {**made, "note": note} if note else made


STANDARD_DRILLS = [
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d001",
        "title": "Forehand to forehand",
        "category": "topspin",
        "level": "beginner",
        "focus": "Forehand consistency",
        "duration_minutes": 10,
        "repetitions": None,
        "equipment": "",
        "instructions": "Rally forehand to forehand on the diagonal at a steady pace. Keep the ball on the "
        "table: aim for 50 in a row before speeding up.",
        "skills": ["forehand", "consistency"],
        "description": "The first rally every player learns. Steady forehand to forehand on the diagonal grooves a repeatable stroke and the timing for everything built on it.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+forehand+to+forehand+drill",
        "coaching_points": "Turn the waist, not just the arm.\nFinish the stroke in front of your forehead.\n"
        "Return to the ready position after every shot.",
        "pattern": [step("partner", "FH", "right", "long"), step("you", "FH", "left", "long")],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d002",
        "title": "Backhand to backhand",
        "category": "topspin",
        "level": "beginner",
        "focus": "Backhand consistency",
        "duration_minutes": 10,
        "repetitions": None,
        "equipment": "",
        "instructions": "Rally backhand to backhand on the diagonal. Start with drives, then let one player "
        "block while the other plays topspin.",
        "skills": ["backhand", "consistency"],
        "description": "The backhand partner of forehand to forehand. A compact, consistent backhand on the diagonal is the base for blocking, driving and later backhand topspin.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+backhand+to+backhand+drill",
        "coaching_points": "Elbow in front of the body.\nMeet the ball at the top of the bounce.\n"
        "Keep the bat angle closed against topspin.",
        "pattern": [step("partner", "BH", "left", "long"), step("you", "BH", "right", "long")],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d003",
        "title": "Falkenberg",
        "category": "footwork",
        "level": "intermediate",
        "focus": "Footwork and pivot",
        "duration_minutes": 12,
        "repetitions": 20,
        "equipment": "",
        "instructions": "Your partner blocks everything to their backhand corner from you. You play a backhand "
        "from your backhand corner, then step round and play a forehand from the same corner, then move "
        "wide and play a forehand from your forehand corner. Repeat without stopping.",
        "skills": ["footwork", "forehand", "backhand", "transition"],
        "description": "A classic footwork exercise created in the 1970s at Sweden's Falkenberg club. It builds lateral movement, balance, and transitions between backhand and forehand strokes.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+falkenberg+drill",
        "coaching_points": "Small steps first, then the big step out wide.\n"
        "Keep your weight on the balls of your feet.\nRecover to the middle after the wide forehand.",
        "pattern": [
            step("partner", "BH", "left", "long", "Backhand diagonal; partner blocks diagonally"),
            step("partner", "FH pivot", "left", "long", "Forehand diagonal; partner blocks straight"),
            step("partner", "FH wide", "right", "long", "Forehand straight; partner blocks diagonally"),
        ],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d004",
        "title": "Forehand from the middle and wide",
        "category": "footwork",
        "level": "beginner",
        "focus": "Side-to-side footwork",
        "duration_minutes": 10,
        "repetitions": 30,
        "equipment": "",
        "instructions": "Your partner blocks alternately to your middle and to your wide forehand. Play every "
        "ball with your forehand to their backhand.",
        "skills": ["footwork", "forehand"],
        "description": "Two-point forehand footwork: the shortest drill that makes you move your feet instead of reaching. Good preparation for the Falkenberg.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+forehand+footwork+drill+two+point",
        "coaching_points": "Move your feet, not just your arm.\nOne side step, never a cross step.\n"
        "Keep the same stroke from both places.",
        "pattern": [
            step("partner", "FH middle", "center", "long"),
            step("partner", "FH wide", "right", "long"),
        ],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d005",
        "title": "Backhand and forehand transition",
        "category": "footwork",
        "level": "intermediate",
        "focus": "Changing wings",
        "duration_minutes": 10,
        "repetitions": 30,
        "equipment": "",
        "instructions": "Your partner blocks alternately to your backhand and your forehand. Play backhand from "
        "the backhand side and forehand from the forehand side, both to their backhand.",
        "skills": ["transition", "footwork", "backhand", "forehand"],
        "description": "Alternating backhand and forehand teaches you to decide early and return the bat to a neutral position, which is where most rallies are won or lost.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+backhand+forehand+transition+drill",
        "coaching_points": "Bat back to neutral in front of you between shots.\n"
        "Decide early which wing to use.\nStay low and balanced.",
        "pattern": [step("partner", "BH", "left", "long"), step("partner", "FH", "right", "long")],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d006",
        "title": "Short backspin serves",
        "category": "serve",
        "level": "beginner",
        "focus": "Serve placement",
        "duration_minutes": 15,
        "repetitions": 60,
        "equipment": "A bucket of balls",
        "instructions": "Serve short backspin so the ball would bounce twice on the far side. Serve 20 to each "
        "of their forehand, middle and backhand. Put a towel or target near the net to aim at.",
        "skills": ["serve", "placement", "third_ball"],
        "description": "Short serves stop the receiver attacking first. Practising placement to three spots gives you serves to set up your third ball.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+short+backspin+serve+practice",
        "coaching_points": "Contact the bottom of the ball with a fast, thin brush.\n"
        "Make the first bounce near the net on your own side.\n"
        "Toss at least 16 cm, straight up.",
        "pattern": [
            step("you", "Short", "left", "short"),
            step("you", "Short", "center", "short"),
            step("you", "Short", "right", "short"),
        ],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d007",
        "title": "Push to push",
        "category": "short_game",
        "level": "beginner",
        "focus": "Backspin control",
        "duration_minutes": 8,
        "repetitions": None,
        "equipment": "",
        "instructions": "Push backhand to backhand, keeping the ball low and in the middle of the table. Then "
        "try to keep every push short enough to bounce twice.",
        "skills": ["short_game", "consistency", "placement"],
        "description": "Pushing is the backbone of the short game. Keeping pushes low and short denies your opponent an easy first attack.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+push+drill+backspin",
        "coaching_points": "Open the bat and brush under the ball.\nStep in with the right foot for short "
        "balls.\nShort backswing, short follow-through.",
        "pattern": [step("partner", "BH push", "left", "half"), step("you", "BH push", "right", "half")],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d008",
        "title": "Backhand flick receive",
        "category": "receive",
        "level": "intermediate",
        "focus": "Attacking short serves",
        "duration_minutes": 10,
        "repetitions": 40,
        "equipment": "A bucket of balls",
        "instructions": "Your partner serves short to your middle. Step in and flick with the backhand to their "
        "backhand. Then let them vary the spin and read it before you flick.",
        "skills": ["receive", "backhand", "reading_spin"],
        "description": "The backhand flick (or banana flick) turns a short serve into an attack. Reading the spin and stepping in early are what make it work.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+backhand+flick+receive+drill",
        "coaching_points": "Step in with the right foot under the table.\nWrist back, then snap forward.\n"
        "Contact at the top of the bounce.",
        "pattern": [step("partner", "BH flick", "center", "short"), step("you", "BH", "right", "long")],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d009",
        "title": "Serve and third-ball attack",
        "category": "match_play",
        "level": "intermediate",
        "focus": "First attack after the serve",
        "duration_minutes": 15,
        "repetitions": 30,
        "equipment": "",
        "instructions": "Serve short backspin. Your partner pushes long to your backhand. Step round and attack "
        "with a forehand topspin to their forehand. Play the point out.",
        "skills": ["third_ball", "serve", "forehand", "topspin"],
        "description": "Serve, receive, attack: the third ball is the server's first chance to attack. This drill rehearses the most common pattern in match play.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+third+ball+attack+drill",
        "coaching_points": "Get ready to move as soon as you have served.\nLift backspin: more upward brush.\n"
        "Aim deep, not hard.",
        "pattern": [
            step("you", "Push", "center", "short"),
            step("partner", "FH pivot", "left", "long"),
            step("you", "FH", "left", "long"),
        ],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d010",
        "title": "Forehand topspin against block",
        "category": "topspin",
        "level": "intermediate",
        "focus": "Topspin consistency",
        "duration_minutes": 10,
        "repetitions": None,
        "equipment": "",
        "instructions": "Play forehand topspin from your forehand corner to your partner's backhand while they "
        "block it back to the same place. Count the rally.",
        "skills": ["topspin", "forehand", "consistency"],
        "description": "Forehand topspin against a steady block builds a consistent, spinny loop and the leg drive behind it.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+forehand+topspin+against+block+drill",
        "coaching_points": "Load on the right leg, transfer to the left.\nBrush forward and up.\n"
        "Relax the arm between shots.",
        "pattern": [step("partner", "FH loop", "right", "long"), step("you", "BH block", "right", "long")],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d011",
        "title": "Backhand block against topspin",
        "category": "block",
        "level": "beginner",
        "focus": "Blocking",
        "duration_minutes": 10,
        "repetitions": None,
        "equipment": "",
        "instructions": "Your partner plays forehand topspin from their forehand corner to your backhand. Block "
        "it back to them, keeping the bat angle steady.",
        "skills": ["blocking", "backhand"],
        "description": "Blocking topspin with a steady bat angle is the simplest defence against attack, and a key skill for partners in every topspin drill.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+backhand+block+against+topspin+drill",
        "coaching_points": "Close the bat angle.\nShort movement, meet the ball early.\n"
        "Absorb the speed instead of hitting.",
        "pattern": [step("you", "FH loop", "left", "long"), step("partner", "BH block", "left", "long")],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d012",
        "title": "Random multiball",
        "category": "multiball",
        "level": "advanced",
        "focus": "Reading and moving",
        "duration_minutes": 15,
        "repetitions": 40,
        "equipment": "Multiball basket, 60+ balls and a catch net",
        "instructions": "A coach feeds balls quickly to random places on your side. Return each with the right "
        "stroke to a target corner. Sets of 20 balls with a rest between.",
        "skills": ["footwork", "reading_spin", "transition"],
        "description": "Random multiball with a coach trains reading, reaction and recovery at a higher pace than a rally can.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+random+multiball+training",
        "coaching_points": "React to the feed, don't guess.\nRecover to the ready position each time.\n"
        "Keep quality up as you tire.",
        "pattern": [
            step("partner", "FH wide", "right", "long"),
            step("partner", "BH", "left", "long"),
            step("partner", "FH middle", "center", "half"),
            step("partner", "Flick", "right", "short"),
        ],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d013",
        "title": "Dynamic warm-up",
        "category": "warm_up",
        "level": "beginner",
        "focus": "Getting ready to play",
        "duration_minutes": 8,
        "repetitions": None,
        "equipment": "",
        "instructions": "Jog on the spot, then arm circles, leg swings, side shuffles, skips and lunges with a twist, about a minute each.",
        "description": "A short dynamic warm-up raises the heart rate and loosens the joints before play. It lowers the risk of strains and makes the first rallies better.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+dynamic+warm+up",
        "skills": ["fitness", "flexibility"],
        "coaching_points": "Start gently and build up.\nMove every joint you will use: ankles, hips, shoulders, wrists.\nFinish slightly out of breath.",
        "pattern": [],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d014",
        "title": "Shadow footwork",
        "category": "off_table",
        "level": "beginner",
        "focus": "Footwork without a table",
        "duration_minutes": 10,
        "repetitions": None,
        "equipment": "",
        "instructions": "Without a ball, play shadow strokes while moving: two side steps and a forehand, two side steps back and a backhand, then a pivot and forehand. Sets of 30 seconds with 30 seconds rest.",
        "description": "Shadow play grooves the footwork patterns of drills such as the Falkenberg without needing a table or partner, so it suits home training and waiting time at the club.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+shadow+footwork",
        "skills": ["footwork", "fitness"],
        "coaching_points": "Stay low with knees bent.\nKeep the bat up in front of you.\nSmall quick steps, never crossing the feet.",
        "pattern": [],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d015",
        "title": "Skipping",
        "category": "off_table",
        "level": "beginner",
        "focus": "Speed and stamina",
        "duration_minutes": 10,
        "repetitions": None,
        "equipment": "A skipping rope",
        "instructions": "Skip for 1 minute, rest 30 seconds; repeat 6 times. Mix two-foot jumps, alternate feet and fast singles.",
        "description": "Skipping builds the light, quick feet and the stamina table tennis rallies need.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+skipping+rope+training",
        "skills": ["fitness", "footwork"],
        "coaching_points": "Stay on the balls of your feet.\nTurn the rope with the wrists, not the arms.\nKeep a steady rhythm.",
        "pattern": [],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d016",
        "title": "Core and leg circuit",
        "category": "off_table",
        "level": "intermediate",
        "focus": "Strength and balance",
        "duration_minutes": 15,
        "repetitions": 3,
        "equipment": "A mat",
        "instructions": "Three rounds of: 30 seconds plank, 12 squats, 10 lunges each leg, 20 seconds side plank each side, 15 calf raises. One minute rest between rounds.",
        "description": "Strong legs and core power the body rotation behind every topspin and keep you balanced when moving wide.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+core+and+leg+workout+for+players",
        "skills": ["fitness"],
        "coaching_points": "Keep your back straight in planks.\nKnees over toes in squats and lunges.\nQuality before speed.",
        "pattern": [],
    },
    {
        "id": "5d0c1e2a-0001-4000-8000-00000000d017",
        "title": "Cool-down stretch",
        "category": "cool_down",
        "level": "beginner",
        "focus": "Recovery",
        "duration_minutes": 8,
        "repetitions": None,
        "equipment": "A mat",
        "instructions": "Walk for a minute, then hold each stretch for 20 to 30 seconds: calves, hamstrings, quads, hips, lower back, chest, shoulders and forearms.",
        "description": "Static stretching after play brings the heart rate down and helps the muscles recover for the next session.",
        "video_url": "https://www.youtube.com/results?search_query=table+tennis+cool+down+stretching",
        "skills": ["flexibility"],
        "coaching_points": "Breathe slowly and don't bounce.\nStretch to mild tension, never pain.\nDrink water afterwards.",
        "pattern": [],
    },
]
