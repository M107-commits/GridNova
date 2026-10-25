const { test, expect } = require("@playwright/test");

async function signup(page, { name, home, email }) {
  await page.goto("/");
  await expect(page.locator("#authScreen")).toBeVisible();
  await page.locator("#showSignup").click();
  await page.locator("#signupName").fill(name);
  await page.locator("#signupHousehold").fill(home);
  await page.locator("#signupEmail").fill(email);
  await page.locator("#signupPassword").fill("GridNova-test-password");
  await page.locator("#signupCity").selectOption("Bengaluru");
  await page.locator("#signupLocality").fill("Indiranagar");
  await page.locator("#signupForm button.primary").click();
  await expect(page.locator("#app")).toBeVisible();
  await expect(page.locator("#authScreen")).toBeHidden();
}

async function signout(page) {
  await page.locator("#signOut").click();
  await expect(page.locator("#authScreen")).toBeVisible();
}

test("desktop: separate buyer and seller accounts, trade ledger, settings, simulator", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-chromium", "Marketplace flow runs once on desktop.");
  const stamp = Date.now();
  const sellerEmail = `seller-${stamp}@example.test`;
  const buyerEmail = `buyer-${stamp}@example.test`;
  await signup(page, { name: "Asha Rao", home: "Rao Household", email: sellerEmail });
  await expect(page.locator("#sidenav [data-page]")).toHaveCount(7);
  await expect(page.locator("#role, #household")).toHaveCount(0);
  await expect(page.locator("#problemTitle")).toContainText("Solar surplus and local demand");
  await expect(page.getByRole("img", { name: "Illustrative neighborhood generation and energy use" })).toBeVisible();
  await page.locator("#startTour").click();
  await expect(page.getByRole("dialog")).toContainText("Your household baseline");
  const tourPages = [
    ["overview", "1 · Your household baseline"],
    ["market", "2 · List real app data as an offer"],
    ["market", "3 · Explore a buyer journey"],
    ["verification", "4 · Review records and impact"],
    ["transactions", "5 · Follow the ledger"],
  ];
  for (let i = 0; i < tourPages.length; i++) {
    const [destination, title] = tourPages[i];
    await expect(page.getByRole("dialog")).toContainText(title);
    await page.getByRole("button", { name: "Open this page" }).click();
    await expect(page.locator("#" + destination)).toHaveClass(/active/);
    await page.getByRole("button", { name: i === tourPages.length - 1 ? "Finish" : "Next step" }).click();
  }
  await expect(page.locator("#dialog")).toBeHidden();

  const seller = await page.evaluate(() => fetch("/api/auth/me").then(r => r.json()));
  await page.locator('#sidenav [data-page="my-energy"]').click();
  await page.locator('#energyEdit [name="generation_wh"]').fill("6000");
  await page.locator('#energyEdit [name="consumption_wh"]').fill("1000");
  await page.locator("#energyEdit button").click();
  await expect(page.locator("#toast")).toContainText("Energy profile saved");
  await page.locator('#sidenav [data-page="market"]').click();
  await page.locator("#listOffer").click();
  await expect(page.getByRole("dialog", { name: "List household surplus" })).toBeVisible();
  const listing = page.locator("#listingForm");
  await listing.locator('[name="quantity_wh"]').fill("1000");
  await listing.locator('[name="price_paise_per_kwh"]').fill("900");
  await listing.locator("button.primary").click();
  await expect(page.locator("#toast")).toContainText("Offer is live");
  const offerId = await page.evaluate(async householdId => {
    const rows = await fetch("/api/offers?seller_household_id=" + householdId).then(r => r.json());
    return rows.sort((a, b) => b.id - a.id)[0].id;
  }, seller.household_id);

  await signout(page);
  await signup(page, { name: "Ravi Shah", home: "Shah Household", email: buyerEmail });
  await page.locator('#sidenav [data-page="my-energy"]').click();
  await page.locator('#energyEdit [name="consumption_wh"]').fill("3000");
  await page.locator("#energyEdit button").click();
  await expect(page.locator("#toast")).toContainText("Energy profile saved");
  await page.locator('#sidenav [data-page="market"]').click();
  await page.locator('[data-purchase="' + offerId + '"]').click();
  await expect(page.getByRole("dialog", { name: "Buy energy" })).toBeVisible();
  const purchase = page.locator("#purchaseForm");
  await purchase.locator('[name="quantity_wh"]').fill("200");
  await purchase.locator("button.primary").click();
  await expect(page.locator("#toast")).toContainText("Purchase added to activity");
  await page.locator('#sidenav [data-page="transactions"]').click();
  await expect(page.locator("#trades tr")).toContainText("Rao Household");
  await page.locator("#trades [data-detail]").first().click();
  await expect(page.locator("#tradeDetail")).toContainText("Trade #");
  await page.locator("#tradeDetail button").click();
  page.once("dialog", dialog => dialog.accept());
  await page.locator("#trades [data-cancel]").first().click();
  await expect(page.locator("#toast")).toContainText("Trade cancelled");

  await page.locator('#sidenav [data-page="settings"]').click();
  await page.locator('#settingsForm [name="preferred_price_paise"]').fill("1350");
  await page.locator("#settingsForm button").click();
  await expect(page.locator("#toast")).toContainText("Settings saved");

  await page.locator('#sidenav [data-page="simulator"]').click();
  await page.locator("#solarInput").evaluate(el => { el.value = "60"; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.locator("#demandInput").evaluate(el => { el.value = "45"; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.locator("#runSimulation").click();
  await expect(page.locator("#simResult")).toContainText("POTENTIAL ENERGY TO SHARE");

  await page.locator('#sidenav [data-page="my-energy"]').click();
  await page.locator("#generationForm [name=quantity_wh]").fill("1200");
  await page.locator("#generationForm button").click();
  await expect(page.locator("#toast")).toContainText("Generation record submitted");
  await page.locator('#sidenav [data-page="verification"]').click();
  await expect(page.locator("#records")).toContainText("pending");
  await expect(page.locator("#verification")).toContainText("not meter- or authority-verified");

  await signout(page);
  await page.locator("#loginEmail").fill(sellerEmail);
  await page.locator("#loginPassword").fill("GridNova-test-password");
  await page.locator("#loginForm button").click();
  await expect(page.locator("#app")).toBeVisible();
  await page.locator('#sidenav [data-page="my-energy"]').click();
  await expect(page.locator("#myOffers article.offer")).toContainText("Open");
  await page.locator("#myOffers [data-cancel-offer]").click();
  await expect(page.locator("#toast")).toContainText("Offer withdrawn");
  await expect(page.locator("#myOffers")).toContainText("Withdrawn");
});

test("mobile: account entry and navigation across all pages", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile-chromium", "Mobile navigation check runs once on mobile.");
  await signup(page, { name: "Nila Menon", home: "Menon Home", email: `mobile-${Date.now()}@example.test` });
  await expect(page.locator("#mobileNav")).toBeVisible();
  for (const destination of ["market", "my-energy", "transactions", "verification", "simulator", "settings", "overview"]) {
    await page.locator('#mobileNav [data-page="' + destination + '"]').click();
    await expect(page.locator("#" + destination)).toHaveClass(/active/);
  }
  await expect(page.locator("body")).toContainText("GridNova is a simulation");
});

