const { test, expect } = require("@playwright/test");

test("desktop: marketplace, idempotency, ledger, verification, settings, simulator", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "Workflow runs once on desktop; mobile has a navigation-specific check.");
  const reset = await page.request.post("/api/reset", { headers: { "X-Demo-Role": "admin" } });
  expect(reset.status()).toBe(200);
  await page.goto("/");
  await expect(page.locator("#household option")).toHaveCount(5);
  await expect(page.locator("#overviewBody")).toContainText("YOUR HOME");
  await expect(page.locator("#sidenav [data-page]")).toHaveCount(7);

  // Increase this fictional seller's production so it has unlisted energy to offer.
  await page.locator("#household").selectOption("5");
  await page.locator('#sidenav [data-page="my-energy"]').click();
  await page.locator('#energyEdit [name="generation_wh"]').fill("7000");
  await page.locator('#energyEdit button[type="submit"], #energyEdit button').click();
  await expect(page.locator("#toast")).toContainText("Energy profile saved");

  // Create an offer through the actual listing dialog.
  await page.locator('#sidenav [data-page="market"]').click();
  await page.locator("#listOffer").click();
  const listedDialog = page.locator("#listingForm");
  await listedDialog.locator('[name="quantity_wh"]').fill("500");
  await listedDialog.locator('[name="price_paise_per_kwh"]').fill("900");
  await listedDialog.locator('[name="expires_in_hours"]').selectOption("12");
  await listedDialog.locator('button[type="submit"], button.primary').click();
  await expect(page.locator("#toast")).toContainText("Offer is live");
  const response = await page.request.get("/api/offers?seller_household_id=5", {
    headers: { "X-Demo-Role": "homeowner", "X-Household-Id": "5" }
  });
  expect(response.ok()).toBeTruthy();
  const sellerOffers = await response.json();
  const offer = sellerOffers.sort((a, b) => b.id - a.id)[0];
  expect(offer.listed_quantity_wh).toBe(500);

  // A UI purchase partially fills the offer. Browser fetches retry an identical
  // request under the same key and then fill the remaining offer quantity.
  await page.locator("#household").selectOption("2");
  await page.locator('#sidenav [data-page="market"]').click();
  await page.locator('[data-purchase="' + offer.id + '"]').click();
  const purchaseDialog = page.locator("#purchaseForm");
  await purchaseDialog.locator('[name="quantity_wh"]').fill("200");
  await purchaseDialog.locator('button[type="submit"], button.primary').click();
  await expect(page.locator("#toast")).toContainText("Purchase added to activity");
  const apiResult = await page.evaluate(async (offerId) => {
    const headers = {
      "Content-Type": "application/json", "X-Demo-Role": "homeowner",
      "X-Household-Id": "2", "Idempotency-Key": "browser-retry-key-0001"
    };
    const body = JSON.stringify({ buyer_household_id: 2, quantity_wh: 100 });
    const request = () => fetch("/api/offers/" + offerId + "/purchase", { method: "POST", headers, body });
    const first = await request(), firstBody = await first.json();
    const retry = await request(), retryBody = await retry.json();
    const fill = await fetch("/api/offers/" + offerId + "/purchase", {
      method: "POST",
      headers: { ...headers, "Idempotency-Key": "browser-full-fill-key-001" },
      body: JSON.stringify({ buyer_household_id: 2, quantity_wh: 199 })
    });
    const final = await fetch("/api/offers/" + offerId + "/purchase", {
      method: "POST",
      headers: { ...headers, "Idempotency-Key": "browser-full-fill-key-002" },
      body: JSON.stringify({ buyer_household_id: 2, quantity_wh: 1 })
    });
    return { firstStatus: first.status, retryStatus: retry.status,
      firstId: firstBody.id, retryId: retryBody.id, fillStatus: fill.status,
      finalStatus: final.status };
  }, offer.id);
  expect(apiResult.firstStatus).toBe(201);
  expect(apiResult.retryStatus).toBe(201);
  expect(apiResult.firstId).toBe(apiResult.retryId);
  expect(apiResult.fillStatus).toBe(201);
  expect(apiResult.finalStatus).toBe(201);
  const left = await page.request.get("/api/offers?seller_household_id=5", {
    headers: { "X-Demo-Role": "homeowner", "X-Household-Id": "5" }
  });
  expect((await left.json()).some((row) => row.id === offer.id)).toBeFalsy();

  // Withdraw a separate listing from the My Energy page.
  await page.locator("#household").selectOption("5");
  await page.locator('#sidenav [data-page="market"]').click();
  await page.locator("#listOffer").click();
  await page.locator('#listingForm [name="quantity_wh"]').fill("300");
  await page.locator('#listingForm [name="price_paise_per_kwh"]').fill("950");
  await page.locator('#listingForm button.primary').click();
  await expect(page.locator("#toast")).toContainText("Offer is live");
  const ownResponse = await page.request.get("/api/offers?seller_household_id=5", {
    headers: { "X-Demo-Role": "homeowner", "X-Household-Id": "5" }
  });
  const ownOffers = await ownResponse.json();
  const withdrawalOffer = ownOffers.sort((a, b) => b.id - a.id)[0];
  await page.locator('#sidenav [data-page="my-energy"]').click();
  await page.locator('[data-cancel-offer="' + withdrawalOffer.id + '"]').click();
  await expect(page.locator("#toast")).toContainText("Offer withdrawn");

  // Find the new offer's ledger item, inspect it, and cancel it in the UI.
  const tradeResponse = await page.request.get("/api/trades?household_id=2", {
    headers: { "X-Demo-Role": "homeowner", "X-Household-Id": "2" }
  });
  const targetTrade = (await tradeResponse.json()).find((trade) =>
    trade.offer_id === offer.id && trade.status === "completed");
  expect(targetTrade).toBeTruthy();
  await page.locator('#sidenav [data-page="transactions"]').click();
  const targetRow = page.locator("#trades tr").filter({ hasText: "#" + targetTrade.id });
  await expect(targetRow).toBeVisible();
  await targetRow.locator('[data-detail]').click();
  await expect(page.locator("#tradeDetail")).toContainText("Trade #" + targetTrade.id);
  page.once("dialog", (dialog) => dialog.accept());
  await targetRow.locator('[data-cancel]').click();
  await expect(page.locator("#toast")).toContainText("Trade cancelled");
  await expect(page.locator("#trades")).toContainText("cancelled");

  // Add a generation entry and review it with the demo verifier role.
  await page.locator('#sidenav [data-page="my-energy"]').click();
  const reference = "E2E-" + Date.now();
  await page.locator('#generationForm [name="certificate_reference"]').fill(reference);
  await page.locator("#generationForm button.primary").click();
  await expect(page.locator("#toast")).toContainText("submitted");
  await page.locator("#role").selectOption("verifier");
  await page.locator('#sidenav [data-page="verification"]').click();
  await expect(page.locator("#records")).toContainText(reference);
  page.once("dialog", (dialog) => dialog.accept("Browser demo review"));
  await page.locator("[data-verify]").first().click();
  await expect(page.locator("#toast")).toContainText("reviewed");

  // Exercise settings and the server-backed simulator.
  await page.locator("#role").selectOption("homeowner");
  await page.locator("#household").selectOption("2");
  await page.locator('#sidenav [data-page="settings"]').click();
  await page.locator('#settingsForm [name="preferred_price_paise"]').fill("1337");
  await page.locator("#settingsForm button.primary").click();
  await expect(page.locator("#toast")).toContainText("Settings saved");
  await page.locator('#sidenav [data-page="simulator"]').click();
  await page.locator("#solarInput").fill("60");
  await page.locator("#demandInput").fill("45");
  await page.locator("#runSimulation").click();
  await expect(page.locator("#simResult")).toContainText("COMMUNITY SHARE POTENTIAL");

  // Verify that the admin demo reset works through its settings control.
  await page.locator("#role").selectOption("admin");
  await page.locator('#sidenav [data-page="settings"]').click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#resetDemo").click();
  await expect(page.locator("#toast")).toContainText("Demo data reset");
  await expect(page.locator("#household option")).toHaveCount(5);
});

test("mobile: all seven sections are reachable at phone width", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile-chromium", "Runs on the mobile viewport project.");
  await page.setViewportSize({ width: 390, height: 844 });
  const reset = await page.request.post("/api/reset", { headers: { "X-Demo-Role": "admin" } });
  expect(reset.status()).toBe(200);
  await page.goto("/");
  await expect(page.locator("#household option")).toHaveCount(5);
  const pages = ["overview", "market", "my-energy", "transactions", "verification", "simulator", "settings"];
  for (const name of pages) {
    await page.locator('#mobileNav [data-page="' + name + '"]').click();
    await expect(page.locator("#" + name)).toBeVisible();
    await expect(page.locator("#" + name + " h1")).toBeVisible();
  }
  await expect(page.locator("#mobileNav")).toBeVisible();
});
