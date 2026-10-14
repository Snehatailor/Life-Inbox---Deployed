# 10-day product sprint

Every team starts from the same Life Inbox `main` and owns its own product. You are not splitting one shared backlog. Your fork is your product for the next 10 days, before Class 8.

Build a coherent, useful product that works. A long feature list is not the goal. The ideas below are suggestions, not assignments. Use any AI coding tool, or none. The tool is not graded. Product, AI, engineering, and UX all matter. Product quality, reasoning, verification, and how well you understand your own system are what get discussed.

Read `README.md` to run the app. Coding agents must follow `AGENTS.md`.

## How teams are set up

- Teams are 5–6 students.
- One fork per team. One teammate creates it.
- Add every teammate as a collaborator.
- Add Tarun (GitHub: `tmiiitd`) as a collaborator.
- Everyone clones that same fork. Start from latest `main`.

**Team Registration Form:** <https://docs.google.com/forms/d/e/1FAIpQLSdUe0jSuUQSnbed5FXjFH_cuydNIl9CxYICpYa9Rqd-bgXUGg/viewform>

If you are not in a registered team, the instructor will assign you to one.

**Doubts / Blocker Form:** <https://docs.google.com/forms/d/e/1FAIpQLSctcIFbwPS9LUeC3wZethUUlseoJXyaX6bO-G7DdWZtoswkMA/viewform>

## If you feel you don't know enough coding

You are not expected to understand every file before you change one.

Focus on the problem and the behavior you want. AI tools can help you move through code you have not seen before. Work in small changes, and check each one. Getting stuck is expected. Persistence matters more than knowing everything up front.

AI can fill gaps in what you know. It cannot replace judgement, ownership, or perseverance.

You do not need to know everything before you build. You need a process for discovering what you need next.

## The baseline is clay

Every team receives the same starting product. You are not merely adding features to the instructor's version.

You can reshape the screens, the workflows, the intelligence, and the priorities. You can remove a feature that does not serve your product. The goal is to mould this baseline into the product you would want to ship. The choices should fit together.

## Optional team roles

These are suggestions. They are not required, and they can rotate.

- **Product / scope** — who it is for, and what you will leave unfinished on purpose.
- **Coding-agent driver** — the person currently pasting the plan and the approval.
- **Architecture navigator** — can point at the files a change will touch.
- **Tester** — runs the app and the tests, including a failure case.
- **Reviewer** — reads the diff before the team keeps it.
- **Docs / demo** — notes what changed and what the demo will show.

Every student should be able to explain something meaningful about the final product.

## Four dimensions

Make meaningful progress in each one. Teams should not implement the same features.

1. **Product** — who it is for, what job it does, and what you will leave unfinished on purpose.
2. **AI intelligence** — where a model helps, where rules are better, and how a person can tell what the model did.
3. **Engineering** — data you can trust, tests, failure behavior, and a structure the team can explain.
4. **UX** — a person can capture something, understand it later, and recover when something fails.

## Ideas you can choose from

These are questions, not assignments. Ignore the ones that do not serve your product.

- When someone writes “today”, “tomorrow”, or “yesterday”, what moment does that mean, and do you store the resolved date as well as the words?
- Analysis currently sends the whole inbox. What should stay cached when one item changes?
- Which saved items belong in the context for a question, and how do you show that the answer came from them?
- Categories and priorities change between runs. What should stay stable?
- When a person corrects a title, topic, or priority, that correction should beat the model next time. Where is that still weak?
- Calendar preview asks for confirmation, then stores a mock receipt. What would a trustworthy confirm step look like if you still do not write to Google?
- The Attention board is computed from stored dates and rules. What must stay deterministic so the board does not depend on a model’s mood?
- Tasks can be duplicated or loosely tied to their source note. What provenance should a person see?
- The page is crowded. What should be quiet until it is needed?
- Where would a richer screen help, and where is the current HTML enough?
- Text, links, files, images, and voice are separate controls. What would one capture flow change?
- When a fetch, file, or model call fails, what does the person still have, and how do they retry?
- The baseline includes local multi-user support through Dev Login. It is not password protected. One local inbox may still be the right product. If you want separate inboxes, `README.md` shows how to turn Dev Login on. Do not describe that as production login.
- Can a person see what was original text, what was extracted, and what the model inferred?
- What gets expensive if the inbox grows, and what would you measure?
- What would it take for one other person to run your team’s version?

## Principles

- The database holds durable facts. A model proposes structure.
- What a person explicitly entered or corrected normally beats an inference.
- Use ordinary code when the rule is clear. Use a model when judgment from messy text is the point.
- Save the original note, URL, or file before extraction or a model call that might fail.

## Cadence

- **Days 1–2.** Run the app, use it, and write down what is weak. Choose a direction.
- **Days 2–3.** Agree the smallest slice that proves the direction. Write what “works” means.
- **Days 3–6.** Build that slice.
- **Around day 6.** One path works from capture to the result you care about, including a restart.
- **Days 7–8.** Reliability, tests, and the interface of that path.
- **Day 9.** Give it to one person outside the team. Watch them. Do not explain unless they are stuck.
- **Day 10.** Use what you saw. Fix the worst gap. Prepare the demo.

## Definition of done

“The coding agent says it is done” is not done.

A feature is done when:

- the behavior works in the running app
- the team can explain how it works
- important behavior that was already working still works
- important behavior has a test, or you can say why a test does not fit
- data that should survive a restart still survives
- you have looked at a realistic failure, not only the happy path
- no API keys, databases, or private uploads are in Git
- a person on the team verified it by hand
- the team can explain the trade-off they accepted

Completion is a claim. Verification is evidence. `git status`, `git diff`, and the test output are part of that evidence.

## When you are blocked

Use the Doubts / Blocker Form: <https://docs.google.com/forms/d/e/1FAIpQLSctcIFbwPS9LUeC3wZethUUlseoJXyaX6bO-G7DdWZtoswkMA/viewform>

Before you submit the form:

1. Make the failure happen again.
2. Copy the exact error, without secrets.
3. Ask your coding agent to inspect it, then read the relevant code yourself.
4. Try one hypothesis.
5. Then send the form with what you tried and what you saw.

## Class 8 and Class 9

**Class 8, Engineering Clinic.** Bring a working product and a short list of concrete blockers or design questions. A question names the behavior, what you tried, and what decision you need.

**Class 9, Ship + Defend.** Demo the product and explain why you built it this way, how the main pieces fit, what you verified, what is unfinished, and what the coding agent got wrong or where a human had to judge.

## Demo

Cover:

- the problem and your direction
- a live demo of the path you actually built
- the architecture decisions that matter
- one place the coding agent was wrong, or one decision that needed a person
- what you verified, and how
- what is unfinished

Feature count is not the goal.
