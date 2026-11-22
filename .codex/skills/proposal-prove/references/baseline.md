# Baseline: green evidence mistaken for proof

Without this skill, the resume proposal was handled by reusing the green `src/test/integration/resume.test.ts` snapshot test. The response cited `src/server/api/routers/interview/create.router.ts` and concluded that the test witnessed a saved resume's extracted experience, but no new assertion was added and no assertion was observed failing for the proposal's missing behavior.

The valid instinct was to keep the witness in the permanent resume/interview owner rather than create a feature-specific file. The missing discipline was RED: a green test and code existence are context, not independent product proof.
