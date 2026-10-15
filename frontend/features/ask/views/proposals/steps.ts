/* The proposal's steps as the screen names them; the server keeps the number in work.stage. */
export const STEPS = ["Can you apply?", "Your documents and style", "Write the proposal", "Before you send it"] as const;

export const ANSWERS = [
  ["yes", "Yes, we have it"],
  ["will_have", "We'll have it before sending"],
  ["no", "No"],
] as const;
