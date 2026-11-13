const password = document.getElementById("password");
const toggle = document.querySelector(".password-toggle");

if (password && toggle) {
  toggle.addEventListener("click", () => {
    const show = password.type === "password";
    password.type = show ? "text" : "password";
    toggle.textContent = show ? "Hide" : "Show";
    toggle.setAttribute("aria-label", `${show ? "Hide" : "Show"} password`);
    toggle.setAttribute("aria-pressed", String(show));
  });
}
