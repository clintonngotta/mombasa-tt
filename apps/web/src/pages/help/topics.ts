import { Building2, CircleUserRound, Medal, Radio, Trophy, Users, Warehouse, type LucideIcon } from "lucide-react"

/** One question in the help centre. `steps` are numbered; `notes` are plain paragraphs after them. */
export type Article = {
  id: string
  question: string
  steps?: string[]
  notes?: string[]
  /** Where to go to do it. */
  link?: { to: string; label: string }
}
export type Topic = { id: string; title: string; icon: LucideIcon; articles: Article[] }

export const TOPICS: Topic[] = [
  {
    id: "tournaments",
    title: "Enter a tournament",
    icon: Medal,
    articles: [
      {
        id: "enter-a-tournament",
        question: "How do I enter a tournament?",
        steps: [
          "Open the Tournaments tab and choose a tournament. Search by its name, its host or the town.",
          "Under Events, choose Enter or see entries on the event you want, such as Men's Singles.",
          "Choose Enter. For doubles you name your partner, and for a team event your players.",
        ],
        notes: [
          "You need an account to enter. Anyone can look at a tournament without one.",
          "If the button isn't there, the page says why: registration hasn't opened yet, has closed, or the event has started.",
        ],
        link: { to: "/tournaments", label: "Find a tournament" },
      },
      {
        id: "entry-status",
        question: "What do Accepted, Pending and Waiting list mean?",
        notes: [
          "Accepted: you have a place in the event.",
          "Pending: this event's organizers approve each entry themselves. Your entry shows the answer as soon as they decide.",
          "Waiting list: the event was full when you entered. If a place opens, the organizers can move you in.",
          "Events with open admission accept you straight away while there are places. Events with organizer approval always start as Pending.",
        ],
      },
      {
        id: "entry-fee",
        question: "How do I pay the entry fee?",
        notes: [
          "The tournament page shows whether it is free or what it costs. The app doesn't take payments: you pay the organizers the way they ask, and they record it.",
          "Being accepted gives you your place. Payment is tracked separately.",
        ],
      },
      {
        id: "check-in",
        question: "How do I check in on the day?",
        steps: [
          "On the tournament's dates, open the tournament, then your event's entries.",
          "Choose Check in now beside your entry.",
        ],
        notes: ["No phone, or no signal? The organizers' desk can check you in instead."],
      },
      {
        id: "withdraw",
        question: "How do I withdraw?",
        steps: ["Open Tournaments. Your entry is listed under Your entries.", "Open it and choose Withdraw, then confirm."],
        notes: ["If you were accepted, withdrawing gives up your place."],
      },
    ],
  },
  {
    id: "follow",
    title: "Follow matches",
    icon: Radio,
    articles: [
      {
        id: "follow-live",
        question: "How do I follow live scores?",
        steps: [
          "Open the Tournaments tab. Tournaments being played now are at the top, marked Live.",
          "Open one. The matches on table right now show at the top with their scores, and update by themselves.",
          "Tap a match for its full scoreboard: games, points, who is serving, time-outs and cards.",
        ],
        notes: ["You don't need an account to follow a published tournament, so you can share the link with family and friends."],
        link: { to: "/tournaments", label: "Open Tournaments" },
      },
      {
        id: "draw-and-results",
        question: "Where are the draw, the results and the order of play?",
        notes: [
          "On the tournament page, each event has Draw and results (brackets, groups and standings) and Order of play (which matches are on which table, and when).",
          "Results appear once the umpire or the results desk confirms them.",
        ],
      },
      {
        id: "my-matches",
        question: "How do I know when and where I play?",
        notes: [
          "Order of play shows your table and time. Notifications about your tournaments are under the bell at the top of the screen. Allow notifications on this device there, so they reach you when the app is closed.",
        ],
        link: { to: "/notifications", label: "Notification settings" },
      },
    ],
  },
  {
    id: "clubs",
    title: "Clubs",
    icon: Users,
    articles: [
      {
        id: "join-a-club",
        question: "How do I join a club?",
        steps: [
          "Open Club, then Find a club.",
          "Type the club's name or your city, or choose Near me to see clubs around you.",
          "Open a club to see where it plays and when it trains, then choose Request to join.",
        ],
        notes: [
          "The club's staff approve requests. Until then it shows as Request pending; once they approve, the club appears under Club.",
          "If the club invited you by email, open the link in the email, or look under Club for your invitations.",
        ],
        link: { to: "/club/find", label: "Find a club" },
      },
      {
        id: "register-a-club",
        question: "How do I register my own club or facility?",
        steps: ["Open Club, then Register a club.", "Enter its name, what it is (a club, a facility, or both) and where it is.", "Save. You become its admin and can invite members and give them roles."],
        link: { to: "/club/new", label: "Register a club" },
      },
      {
        id: "club-or-team",
        question: "What is the difference between a club and a team?",
        notes: [
          "A club is a place people train at: it has a hall or tables you can find on the map.",
          "A team is players who play together without a training place of their own. It has members, roles and its own ranking, and a home town instead of a map location.",
          "You can belong to a club and a team at once. Each has its own tab: Club and Team.",
        ],
      },
      {
        id: "form-a-team",
        question: "How do I form or join a team?",
        steps: [
          "Open Team. On a phone it may be under More.",
          "To join one, choose Find a team, search by name or city, and choose Request to join.",
          "To start one, choose Form a team, enter its name and home town, and save. You become its admin and can invite your teammates.",
        ],
        notes: ["Rankings has a Teams tab: a team's points are the combined ratings of its members."],
        link: { to: "/team", label: "Open Team" },
      },
      {
        id: "more-than-one-club",
        question: "Can I belong to more than one club?",
        notes: ["Yes. Use the club name at the top of the screen to switch between them. The Club tab and its menus follow the one you picked."],
      },
    ],
  },
  {
    id: "places",
    title: "Find clubs and places near you",
    icon: Warehouse,
    articles: [
      {
        id: "search-by-city",
        question: "How do I find clubs or places to play in a city?",
        steps: [
          "Open Find a club, or Find a place to play. A switch at the top moves between the two.",
          "Type the city or town, for example Mombasa, and choose Search.",
        ],
        notes: ["To browse a whole region instead, choose Choose a region or city and pick from the lists."],
        link: { to: "/facilities", label: "Find a place to play" },
      },
      {
        id: "near-me",
        question: "How do I see what is near me, for example within 300 m?",
        steps: [
          "On either finder, choose Near me and allow the app to use your location when your browser asks.",
          "Pick how far to look: 300 m, 1 km, 5 km, 10 km or 25 km. The nearest come first, each with its distance.",
          "For places to play, tick Open now to hide the ones that are closed.",
        ],
        notes: [
          "Your location is used for that search only. It isn't saved, shown to anyone or kept on your device.",
          "Only clubs and halls that have set their map location appear in a Near me search. If you expected one and don't see it, search by city instead.",
          "Indoors, a phone can be unsure of its position by more than 300 m. The page tells you when that is the case: choose a wider distance.",
        ],
      },
      {
        id: "location-blocked",
        question: "Near me says location is switched off. What now?",
        notes: [
          "Your browser has blocked location for this site. Open the site's settings from the padlock beside the address, set Location to Allow, and try again. On a phone, also check that location is on in the phone's own settings.",
          "You can always search by city without sharing a location.",
        ],
      },
      {
        id: "put-us-on-the-map",
        question: "How do I get my club or hall into Near me searches?",
        notes: [
          "A club's admin opens Club and adds the map position to the club's location, then chooses Save location. Use my current location fills it in while you are standing at the club.",
          "For a hall, open Venues (or Branches), edit the venue and do the same. A facility branch also needs Who finds this branch set to members or everyone.",
        ],
      },
      {
        id: "visit-a-facility",
        question: "What does a facility's page tell me?",
        notes: ["Its address and directions, opening hours and closures, tables, house rules, what day and longer passes cost, and what is coming up. Where the facility allows it, you can ask to book a table from the same page."],
      },
    ],
  },
  {
    id: "organize",
    title: "Run a tournament",
    icon: Trophy,
    articles: [
      {
        id: "run-a-tournament",
        question: "How do I create a tournament?",
        steps: [
          "Open Tournaments and choose New tournament. Enter the name, the dates and the venue, then Create draft. Only your competition staff see a draft.",
          "On the draft, choose Add event for each event, such as Men's Singles: its format, how many can enter and whether entries are accepted automatically or approved by you.",
          "Choose Publish tournament. Players can now find it and enter.",
        ],
        notes: [
          "New tournament shows when you are a club's admin, or have a role there that manages competitions. No club yet? Register one first: you become its admin.",
          "Publishing needs a venue and at least one event. Add venues and their tables under Club, Venues and tables.",
          "A local tournament publishes straight away. Regional, national and international ones are approved first by the officials for that level.",
        ],
        link: { to: "/club/tournaments", label: "Your tournaments" },
      },
      {
        id: "free-or-paid",
        question: "Can I charge a registration fee?",
        notes: ["Yes. Choose Paid on the tournament form and set the fee. The app shows it to players and lets you track who has paid; it doesn't collect the money."],
      },
      {
        id: "draw-and-schedule",
        question: "How do the draw and the schedule work?",
        notes: [
          "When entries are in, open the event's Draw desk. The app recommends seeds by rating and builds the draw; you can change it before you publish it.",
          "It then recommends a schedule and tables from the draw. Review it, edit what you need, and publish.",
          "On the day, choose Start tournament, start each event, and use the tournament's dashboard for check-in, calling matches to tables and results.",
        ],
      },
      {
        id: "who-can-help",
        question: "How do I let others help run it?",
        notes: ["Give members of your club a role that includes competitions, results or umpiring under Club, Roles and permissions. Umpires score on their own phones, and scoring keeps working if the connection drops."],
      },
    ],
  },
  {
    id: "facilities",
    title: "Run a facility",
    icon: Building2,
    articles: [
      {
        id: "set-up-a-facility",
        question: "How do I list my hall so players can find it?",
        steps: [
          "Register it from Club, Register a club, choosing Facility (or Club and facility).",
          "Add each branch under Branches: its address, map position, tables and opening hours.",
          "Under Who finds this branch, choose everyone or members only. A new branch is hidden until you do.",
        ],
      },
      {
        id: "door",
        question: "How do passes and door payments work?",
        notes: ["Staff set day and longer passes for each branch and record each visit at the door, with cash or an M-Pesa reference. The app keeps the record; it doesn't process the payment. Players see only their own visits, under Profile."],
      },
    ],
  },
  {
    id: "account",
    title: "Your account and the app",
    icon: CircleUserRound,
    articles: [
      {
        id: "install",
        question: "Can I put the app on my phone's home screen?",
        notes: ["Yes. Open Profile and follow Install there. It then opens like any other app."],
        link: { to: "/profile", label: "Open Profile" },
      },
      {
        id: "offline",
        question: "What happens when I lose signal?",
        notes: ["Pages you have opened stay readable, and changes you make are kept on the device and sent when you are back online. Profile, Waiting to sync shows anything not yet sent."],
      },
      {
        id: "password",
        question: "I forgot my password.",
        notes: ["On the log-in page choose Forgot password? and enter your email. If it belongs to an account, a link to set a new password is sent to it."],
        link: { to: "/forgot-password", label: "Reset your password" },
      },
      {
        id: "quick-score",
        question: "Can I score a casual game without an account?",
        notes: ["Yes. Quick Score keeps score on your phone for a friendly game. It isn't rated and nothing is booked."],
        link: { to: "/quick-score", label: "Open Quick Score" },
      },
      {
        id: "ratings",
        question: "Where do my rating and ranking come from?",
        notes: ["From your confirmed tournament matches. Rankings lists players by rating; your own history is under Profile, My ratings."],
        link: { to: "/rankings", label: "See the rankings" },
      },
    ],
  },
]

/** The words of an article, for searching. */
export const articleText = (a: Article) => [a.question, ...(a.steps ?? []), ...(a.notes ?? [])].join(" ").toLowerCase()
