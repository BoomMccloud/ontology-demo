# OntoLog mobile app

## Interactive prototype

[Open the local HTML prototype](../../prototypes/ontolog.html) in a browser. Choose **Start empty** to try the first-note journey. AI replies and ontology processing are simulated.

The prototype follows this file and uses the Margin notes direction below. It covers Recent, capture with processing status, company and theme pages with disagreement and sources, the note reader, Ontology with search, and chat with **Save as note**. It is the starting point for design work, not a finished design.

## Outcome

An analyst can capture a note on their phone, see it processed, open the companies and themes it touched, check the sources behind each View, and ask the research agent to verify or refute what they heard. They can save a cited answer from that conversation as a new note. Every note goes through the same processing as notes from the web app.

## Benefits

Analysts can capture details while a meeting or channel check is fresh, then check the underlying evidence from their phone without waiting to get back to a desk.

## Approach

The first release is a mobile web app with its own design, templates, and CSS. It shares nothing visual with the desktop app. It runs in the same FastAPI server as a separate web module under `/m`, with its own navigation and design tokens. It reads through the same services the desktop pages use, and it writes through the existing JSON routes: `POST /api/notes`, `POST /api/notes/process`, `GET /api/jobs/{job_id}`, and `POST /api/chat`. This mobile web app is the UX template. A native app comes later and follows the flows proven here.

## Design principles

- Notes are the source of truth. The ontology is built from notes, so the app never edits a View or consensus directly. To record a judgment, the analyst saves a note.
- Analysts capture raw notes, including bullets, meeting quotes, and pasted excerpts. The worker extracts entities, events, views, and relationships asynchronously.
- Use the ontology's own terms in the UI: Company, Theme, Entity, Event, View, and consensus. The mobile and web apps describe the same records with the same names.
- Show disagreement as it exists in the graph. When Views on the same company or theme have opposing stances, show both with their sources. The analyst resolves it by asking the agent and saving a note.
- The visual design is mobile-only and chosen from scratch. See Visual design below.

## Vocabulary

The earlier draft used its own terms. They map to the ontology as follows.

| Earlier draft | Ontology |
| --- | --- |
| Thesis | Theme |
| Factor or entity | Entity that is not a company |
| Belief or claim | View, with stance, status, and `as_of` |
| Current beliefs | Consensus synthesis |
| Semantic change | A new Event or View from a recently processed note |
| Source | Note |

## Navigation

Recent and Ontology are two ways into the same company and theme pages. The three-slot bottom bar changes with the screen.

| View | Left | Center | Right |
| --- | --- | --- | --- |
| Recent, Ontology, or Note | **Recent** opens the home screen | **+** opens capture | **Ontology** opens the directory and search |
| Company or Theme | **Sources** jumps to the notes behind this page | **+** captures a note for this company or theme | **Chat** opens or resumes research chat over this page |

- **Recent** is the home screen. It lists companies and themes touched by recently processed notes, newest first.
- **Ontology** lists companies, themes, and entities, with a search field on top. Search uses the same search service as the web app, so results match.
- **+** opens capture. On a company or theme page, the note carries that page as a hint.

Chat opens as a panel over the current page, above the bottom bar, and can expand to full height. Minimizing it keeps the analyst's place, and reopening it resumes the conversation. A note page has a **Research this note** action that opens chat focused on that note.

The top **Back** control names and returns to the actual previous screen. After opening a company from Ontology and then one of its notes, Back returns to the company, then to Ontology. With no previous screen, the top left shows the OntoLog name, which returns to Recent.

## Visual design

The direction is **Margin notes**: the words from the source note lead every screen. It is a starting point for the designer, who can change any value here.

- **Evidence first.** Rows show the sentence from the note itself, set in serif italic and indented behind a 2px rule, like a note in a margin. The cited note's title and age sit under the quote. Summaries and labels stay in the sans.
- **Color means stance only.** The rule beside a quote is amber for a View that challenges another, green for support, and slate for a routine addition. Node type is a lowercase word next to the name (company, theme, entity), not a color.
- **Rows, not cards.** Content is a single left-aligned column with hairline rules between rows and a heavier rule under each section heading.
- **Light first, dark supported.** Both modes use the same tokens.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| Paper | `#EDF0F4` | `#10151F` | Page background |
| Sheet | `#F7F8FA` | `#171E2B` | Capture and chat sheets |
| Ink | `#14213D` | `#E4E9F1` | Text, primary button, section rules |
| Ink 2 | `#5B6B85` | `#93A1B8` | Metadata, node type, citations |
| Rule | `#C3CAD5` | `#2A3446` | Hairlines between rows |
| Challenge | `#B45309` | `#F0A35A` | Challenging View, processing dot |
| Support | `#047857` | `#4CC79A` | Supporting View |
| Routine | `#94A3B8` | `#64748B` | Routine addition |

Type is Inter Tight for the interface and Source Serif 4 for anything quoted from a note. The scale is 28px for page titles, 19px for empty-state headings, 15px for body and quotes, 13px for metadata and section headings, and 12px for citations. A note's full text is 17px serif. The page gutter is 16px and the bottom bar is 64px.

Stance comes from the View's stance and sentiment as extraction records them. Detecting whether new evidence corroborates or challenges an existing claim belongs to Evidence Intake in [Claim Graph Refinements](refinements.md). Until then, a challenge marker means only that extraction recorded opposing Views.

## User journeys

### Cold start

1. The analyst opens an empty Recent screen and taps **+** to write or paste a note.
2. **Process** queues the note. The analyst sees its job status and can keep using the app.
3. When processing finishes, the companies and themes from the note appear in Recent. The analyst opens one to see what was extracted and follows it back to the note.

### Daily use

1. The analyst opens a company or theme from Recent or Ontology. The page shows the consensus, recent Events and Views, and the notes behind them.
2. **Sources** jumps to that item's notes. The analyst opens a note to read it, see its processing status, and inspect what was extracted from it.
3. The analyst taps **+** to log new information for the current item. The worker processes it and the item moves to the top of Recent.

### Deep research

1. The analyst taps **Chat** on a company or theme page. The agent uses the page, its Views, and the notes behind them. From a note, **Research this note** focuses chat on that note. In capture, **Research** saves the note without processing it and opens chat focused on it.
2. The analyst asks the agent to verify or refute the information. The agent cites the notes it uses and helps identify counterevidence or what would settle an open question.
3. The analyst saves a reply as a note, editing it first if needed. The note keeps the agent's citations and goes through normal processing.

### Capture a supplier conversation on the go

1. Leaving a supplier meeting, an analyst opens OntoLog and dictates a short note with the phone's keyboard. The supplier says customers are asking about later delivery dates, but there is no confirmed change to the planned data center rollout.
2. The analyst saves the note, sees that it is queued, and puts their phone away.
3. Once processing is complete, they open the relevant company or theme, tap **Chat**, and ask, "What else have we heard about the rollout timing?"
4. The agent summarizes the relevant research and cites the notes it used. The analyst opens an earlier note to check whether it described the same customers.

## Screen details

- **Capture.** A slide-up sheet with a title and a text body. Voice uses the phone's dictation keyboard. For a link, the analyst pastes the relevant excerpt along with the URL. Capture from a company or theme page passes that page as a hint.
- **Recent.** Each row shows the item's icon, name, type, its newest Event or View, time since that note was processed, and the note it came from. No per-user state is needed.
- **Company or Theme.** Consensus first, then recent Events and Views with their markers, then Sources. When two Views disagree, show both, each with its quote, note, and date. For example, a View that gross margin will exceed 65% sits next to a newer View citing interposer costs that could bring it to about 52%.
- **Note.** The note text, its processing status, and what was extracted from it, with Process available when the note is not processed.
- **Chat.** The existing research agent in a sheet, with a **Save as note** action on each reply.

## What is new versus what exists

These already work on the server and the mobile screens reuse them: the note paste, Process, job status, and chat JSON routes, the search service, the research agent with citations, and the view models behind the company, theme, and note pages.

These are new:

- The `/m` web module: its own templates, CSS, design tokens, navigation, and the bottom bar that changes with the screen.
- The Recent screen.
- A page hint on captured notes. Today every pasted note is saved under `_general/`.
- **Save as note** on a chat reply, keeping its citations.

## Phases

1. **Mobile web app.** Everything above.
2. **Watchlist.** Replace Recent with a radar of items the analyst tracks, with unreviewed changes and today's alerts. This needs a tracked-item list, per-user review state, and Evidence Intake from [Claim Graph Refinements](refinements.md) to tell corroboration from challenge.
3. **Native app.** Follows the flows proven in the mobile web app and adds the share sheet, in-app voice recording, and push notifications for finished processing.
4. **Login.** Put access control in front of the deployed site. Until then, anyone with the URL can paste notes and queue jobs, as the web app allows today.

## Out of scope for the first release

- **Accept & Merge.** It would edit Views directly, which breaks the rule that the ontology comes from notes. Saving a chat reply as a note does the same job.
- **Graph canvas and Extracted Edges.** They stay on the desktop `/ontology` page.
- **Fetching linked URLs and transcribing recordings.** The analyst supplies the excerpt or dictates.
- **Market developments as an input.** There is no source for them in the system yet.

## Known limits

Chat sessions live in server memory and are capped at 50. A server restart loses the conversation the analyst would resume from their phone. Chat needs persistence before resume can be relied on.

## Open product choices

- How long a window should Recent cover, and should it group by company and theme or show one row per note?
- Should **Save as note** save the reply as written, or open it in capture so the analyst always edits first?
