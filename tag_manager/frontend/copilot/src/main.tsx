import { createRoot, type Root } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

let root: Root | null = null;

export function mount(el: HTMLElement) {
  unmount();
  root = createRoot(el);
  root.render(<App host={el} />);
}

export function unmount() {
  if (root) {
    root.unmount();
    root = null;
  }
}
