const url = process.env.APP_URL || "http://localhost:3000";

setTimeout(() => {
  console.log("");
  console.log("Auto Literature Review is starting.");
  console.log(`Browser: ${url}`);
  console.log("Shutdown: press Ctrl+C in this terminal to stop the API and web servers.");
  console.log("");
}, 500);
