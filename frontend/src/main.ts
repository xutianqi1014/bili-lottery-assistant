import "./styles.css";
import { bootstrap } from "./app/bootstrap";

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("APP_ROOT_MISSING");
void bootstrap(root);

