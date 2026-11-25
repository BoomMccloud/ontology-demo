# OntoLog mobile app

## Interactive prototype

[Open the local HTML prototype](../../prototypes/ontolog.html) in a browser. It starts on the SRAM Latency thesis with research chat open. Company and thesis views use **Sources · + · Chat**, and the top Back control follows the route the analyst took. Choose **Start empty** to try the first-note journey. AI replies and ontology processing are simulated.

## Outcome

An analyst can start with a link or note and see the ontology engine surface companies and theses in the Watchlist. As new evidence arrives, they can check what changed, trace claims to their sources, and ask the AI to verify or refute the new information. They can review and save a claim from that discussion as a research note. Notes enter the same research workflow used by the web app.

## Benefits

Analysts can capture details while a meeting or channel check is fresh. They can then see which companies, theses, and factors deserve attention and check the underlying evidence from their phone.

## Design principles

- Analysts capture raw notes, including bullets, meeting quotes, web clips, and voice. The ontology engine extracts entities, relationships, and state changes asynchronously.
- The Watchlist is a radar for changes in tracked companies, theses, and factors. Recent notes and market developments surface through their effect on what the analyst is tracking.
- Show semantic changes such as a revised margin target, a new supplier dependency, or evidence that strengthens or weakens a thesis.
- Make contradictions actionable. Ground debate in the active change and its sources, then let the analyst commit a synthesis as a new note.
- Use a restrained dark mode with Swiss typography, clean borders, compact badges, and enough whitespace to scan dense research on a phone.

## Navigation

Watchlist and Ontology are two ways into the same company and thesis detail views. The three-slot bottom bar changes with the screen.

| View | Left | Center | Right |
| --- | --- | --- | --- |
| Watchlist, Ontology, or Source Detail | **Watchlist** opens the home radar | **+** opens capture | **Ontology** opens global research and extracted relationships |
| Company or Thesis Detail | **Sources** jumps to the evidence on the current detail screen | **+** captures a source for this company or thesis | **Chat** opens or resumes research chat over the detail screen |

The top **Back** control returns to the actual previous screen. For example, after opening a company from Ontology and then opening one of its sources, Back returns to the company, then to Ontology. Chat opens as a sheet over the current screen. Minimizing it preserves the analyst’s place in the detail view, and reopening it resumes the conversation.

## Visual encoding

| Node type | Accent | Background tint | Icon | Examples |
| --- | --- | --- | --- | --- |
| Company | Electric blue `#3B82F6` | Blue at 12% opacity | Building or briefcase | Groq, Tenstorrent, Cerebras |
| Thesis | Violet `#A855F7` | Violet at 12% opacity | Target or lightbulb | Open-Weights Parity, SRAM Latency |
| Factor or entity | Emerald `#10B981` | Emerald at 12% opacity | Network, person, or factor icon | TSMC CoWoS Allocation, key executives |

State changes have their own markers. `⚡` and amber `#F59E0B` indicate a contradiction or tension. `↑` and green `#10B981` indicate validation or support. `•` and muted slate `#475569` indicate routine additions.

## User journeys

### Cold start

1. The analyst opens an empty Watchlist and taps **+** to paste a link, write a note, or attach a file.
2. **Process source** queues ontology building. The analyst sees the source’s processing status and can keep using the app.
3. When processing finishes, the companies and theses identified from the source appear in the Watchlist. The analyst can open an item to see what was extracted and follow it back to the original source.

### Daily use

1. The analyst opens a company or thesis from the Watchlist or Ontology. The detail view shows current beliefs, recent semantic changes, and related research.
2. **Sources** jumps to that item’s evidence. The analyst can open a source to read the original material, see its processing status, and inspect its links to the ontology.
3. The analyst taps **+** to log new information for the current item. The ontology engine processes it asynchronously and updates the relevant companies and theses. The Watchlist surfaces items with recent changes.

### Deep research

1. The analyst opens **Chat** from a company or thesis, or attaches a note with **+** and chooses **Research**. The conversation uses the company or thesis, its current claims, and relevant evidence. An attached note or selected source gives the conversation a specific focus. If a source has no company or thesis yet, **Research source** opens chat over Source Detail.
2. The analyst asks the AI to verify or refute the information. The AI cites the research it uses and helps the analyst identify counterevidence or what would resolve an open question.
3. The analyst drafts, edits, and saves a new claim or belief as a research note. The note keeps its source citations and goes through the same ontology processing workflow as other captured research.

### Capture a supplier conversation on the go

1. Leaving a supplier meeting, an analyst opens OntoLog and writes a short note. The supplier says customers are asking about later delivery dates, but there is no confirmed change to the planned data center rollout.
2. The analyst saves the note, sees that it is queued for processing, and puts their phone away.
3. Once processing is complete, they open the relevant company or thesis, tap **Chat**, and ask, “What else have we heard about the rollout timing?”
4. The agent summarizes the relevant research and cites the notes it used. The analyst opens an earlier note to check whether it described the same customers.

## Additional screen details

- **Capture.** The slide-up sheet accepts notes, links, and file attachments. The capture brief also includes voice recording. The prototype offers a sample note for trying the flow.
- **Watchlist.** The draft calls for a tracked-item count, live search, and filters for All, Shifts (Unreviewed), Companies, Theses, and Entities. An amber alert strip summarizes changes detected today. Cards show an item’s icon, name, type, latest semantic change, time since the change, and source citation, with stage, round, and linked thesis where relevant.
- **Company or Thesis Detail.** Show semantic changes alongside the current beliefs they affect. For a contradiction, show the prior belief in red with a strikethrough, the new claim in green, and the original quote with its note ID and timestamp. For example, a margin target above 65% is challenged by a source claiming interposer costs could bring gross margin to about 52%.
- **Ontology Explorer.** The draft includes entity directories, a physics-based **Graph Canvas** that clusters companies, theses, and factors by relationship weight, and **Extracted Edges** with subject, predicate, object, and confidence.

## Open product choices

- Which parts of the three journeys should ship first? Capture, processing status, and cited follow-up are one possible first release. Watchlist change alerts, claim review, and graph exploration can be considered separately.
- What does **Accept & Merge** do when the new claim conflicts with the baseline? Should it replace the prior belief, retain both claims while marking one current, or record the analyst's judgment separately?
- Which inputs feed the Watchlist radar? The brief includes both new notes and market developments. How market developments enter the workflow is open.
- For URLs and voice, should the initial capture flow retrieve the linked content and transcribe recordings, or let the analyst supply the excerpt or transcript?
