import preact from "eslint-config-preact";

export default [
  {
    ignores: ["dist/**", "node_modules/**"],
  },
  ...preact,
];
