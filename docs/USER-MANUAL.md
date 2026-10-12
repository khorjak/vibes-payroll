# Payroll User Manual

A guide for the people who use the Payroll application day to day. For diagrams of how the pieces fit together, see [PROCESS-FLOW.md](PROCESS-FLOW.md).

Button and menu names below match the screens as closely as possible. If a button is missing for you, your role probably does not allow that action (see [Roles](#2-roles-and-what-you-can-do)).

## Contents

1. [Getting started](#1-getting-started)
2. [Roles and what you can do](#2-roles-and-what-you-can-do)
3. [Finding your way around](#3-finding-your-way-around)
4. [Setting up a company (admins)](#4-setting-up-a-company-admins)
5. [Managing users (admins)](#5-managing-users-admins)
6. [Tax settings (admins)](#6-tax-settings-admins)
7. [Managing employees](#7-managing-employees)
8. [Running payroll](#8-running-payroll)
9. [Off-cycle payments and bonuses](#9-off-cycle-payments-and-bonuses)
10. [Voiding a paycheck](#10-voiding-a-paycheck)
11. [Pay stubs](#11-pay-stubs)
12. [Reports](#12-reports)
13. [Year-end checklist](#13-year-end-checklist)
14. [Troubleshooting](#14-troubleshooting)
15. [Things to know](#15-things-to-know)

---

## 1. Getting started

**Signing in.** Open the site address your administrator gave you and enter your username and password. After five wrong attempts within five minutes, sign-in is blocked for that username from that computer. Wait a few minutes and try again.

**First-time administrator.** On first start, the system creates one administrator account. The username and password come from the site's configuration, not from this manual. Sign in, then:

1. Go to **Users** and create real accounts for everyone.
2. Reset the initial administrator's password to something only you know.

**Signing out.** Use the sign-out control in the navigation bar, especially on shared computers.

**Passwords.** Must be at least 8 characters. Only an administrator can reset a password, so ask one if you are locked out.

## 2. Roles and what you can do

Every user has one role. Your role applies to every company you are assigned to.

| Role | Intended for | Can do |
|---|---|---|
| **Read-only** | Owners, auditors | View everything they can access. Change nothing. |
| **Preparer** | Payroll clerks | Everything read-only can, plus add and edit employees, tax elections, benefit enrollments, garnishments and time off policies and balances; create pay periods and bonus runs; enter timesheets; calculate the draft payroll; create off-cycle payments. |
| **Approver** | Payroll managers | Everything read-only can, plus approve a payroll run, mark it paid, and void a paycheck. |
| **Admin** | Whoever runs the system | Everything, plus company, benefit plan and workers comp setup, user management, and yearly tax settings (wage bases, federal and Oklahoma withholding tables). |

Preparing and approving are separate on purpose, so one person cannot both build and release a payroll. Give a person both roles only if you accept that. An admin can do both.

**Company access** is separate from role. A non-admin user only sees the companies an admin assigned to them. If you see nothing at all, you have not been assigned a company; ask an admin. Admins see every company.

## 3. Finding your way around

The left navigation has: **Dashboard**, **Employees**, **Companies**, **Users** and **Tax Settings** (admins only), **Pay Runs**, and **Reports**.

**On a phone** (screens narrower than a tablet), the navigation is hidden to leave room for the page. Tap the menu button (three lines) at the top left to open it; tap a page, the close button, the dimmed area beside it, or press Esc to close it. Wide tables (pay runs, reports, users and so on) scroll sideways inside their box: swipe left on the table to see the remaining columns. Forms stack their fields in a single column. To save room, a few less-used columns are left out on a phone (they always appear on a wider screen): Department and Hire Date on **Employees**; Pay Period, Frequency and Checks on **Pay Runs**; Pre-tax Ded., Taxes and Check # on a pay period's paychecks; Created on **Users**. Tap **Show all columns** above any of these tables to bring them back, then swipe sideways to see them; **Fewer columns** hides them again. Your choice applies to all four tables and is remembered on that phone.

**Dashboard.** Shows three counts: active employees, companies, and open pay runs, with quick actions to add an employee or start a pay period.

**Switching company.** If you can access two or more companies, a company switcher appears in the navigation. The company you pick is your *active company*. Lists (employees, pay periods) and reports default to it. Many lists also let you widen to all companies you can access. If you can access only one company, there is no switcher.

**Search and filters.** The employee list can be searched by first name, last name or department, and filtered by status.

## 4. Setting up a company (admins)

Company setup is admin-only because it affects every payroll.

### Add a company

1. **Companies → New Company**.
2. Fill in:
   - **Name** (required).
   - **EIN**, address, city, state, ZIP.
   - **Pay frequency**: weekly, biweekly, semi-monthly or monthly. This is the default for employees who have no frequency of their own.
   - **SUTA rate**: the company's Oklahoma state unemployment rate. If left blank, payroll uses 2.7%. Set this to your actual rate from your notice.
   - **Workers comp policy** number.
3. Save. The new company becomes your active company.

### Add workers compensation codes

Workers comp codes belong to one company. Changing a rate in one company never affects another.

1. Open the company, then its workers comp codes page.
2. **Add WC Code**: enter the NCCI class code, a description, and the rate per $100 of wages.
3. Use **Edit** to change a rate. The new rate applies to paychecks calculated afterwards.

### Add benefit plans

1. Open the company, then its benefit plans page.
2. **Add Benefit Plan**: name; type (health, dental, vision, FSA, HSA, traditional 401(k), Roth 401(k), life insurance, other); employee contribution type and amount (a percent plan's amount and both match percentages must be between 0 and 100); whether it is **pre-tax**; and optional employer match percentages.
3. Use **Edit** to change a plan, or the toggle to make it inactive. An inactive plan is no longer deducted.

**How contributions work.**
- **Fixed:** the amount is dollars per pay period.
- **Percent:** the amount is a percent of that paycheck's gross pay. A 5% plan takes $125.00 from a $2,500.00 paycheck.
- **Employer match:** "match percent" is how much of the employee's contribution the company matches, and "cap percent" is the most of gross pay that counts. A 100% match with a 4% cap on a $2,500.00 paycheck adds at most $100.00. The match appears under employer costs on the paycheck screen and the pay stub, is included in the total employer cost, and is not taken from the employee.
- **What pre-tax does.** Pre-tax health, dental, vision, FSA, HSA and other cafeteria-style plans lower federal and Oklahoma income tax wages *and* Social Security, Medicare, FUTA and SUTA wages. A **traditional 401(k)** lowers income tax wages only: Social Security, Medicare, FUTA and SUTA are still figured on the full amount. Roth 401(k) is post-tax and lowers nothing.
- An employee's **override** (set when enrolling them) uses the same unit as the plan: dollars for a fixed plan, a percent (0 to 100) for a percent plan. An override of 0 means no deduction for that employee.

## 5. Managing users (admins)

**Users** lists everyone with their role, active status, and company access.

**Add a user.** **Users → New**: enter a username, an initial password (8+ characters), a role, and tick the companies they may access. Admin accounts need no company ticks.

**Edit a user.** Change role, active status, and company access. Removing a company takes effect immediately, on the person's next click.

**Reset a password.** Choose **Reset Password** on the user, then enter a new password (8+ characters). Tell the person through a private channel.

**Safeguards.**
- You cannot demote or deactivate the last active admin.
- Reactivating a deactivated non-admin does **not** restore their company access. Re-assign companies yourself; the list shows an amber "None" for such accounts. This is deliberate, because accounts can view Social Security and bank data.

## 6. Tax settings (admins)

Some tax figures change every year. **Tax Settings** (admins only) holds them by year:

- **Social Security wage base**: the wage limit for Social Security tax, published by the Social Security Administration each October for the following year (search "contribution and benefit base" on ssa.gov).
- **Oklahoma SUTA wage base**: the "Taxable Wage Base" on the Oklahoma Employment Security Commission's *Important Numbers* sheet for the year, published each winter (oklahoma.gov/oesc).
- **Federal withholding tables**: the IRS Publication 15-T *Annual Percentage Method Tables* for automated payroll (Worksheet 1A), published each December (irs.gov/publications/p15t).
- **Oklahoma withholding tables**: *Table 7: ANNUAL Payroll Period* in the Oklahoma Tax Commission's Packet OW-2, plus the annual withholding allowance amount, published each November (oklahoma.gov/tax).

Each paycheck uses the figures for the calendar year of its pay date. The wage bases for 2024 to 2026 and the federal and Oklahoma tables for 2025 and 2026 come with the system.

**Add next year's wage bases.** Fill in **Add or update a year** with the year and both wage bases and choose **Save**. Amounts can be typed with or without `$` and commas. Values outside $1,000 to $1,000,000 are refused.

**Enter next year's federal tables.** Choose **Enter tables** on the year (or the link in the warning) to open the table form. It has two line 1g amounts and six tables of 8 rows: *STANDARD* and *Form W-4, Step 2, Checkbox* schedules, each for Married Filing Jointly, Single or Married Filing Separately, and Head of Household, laid out as in Publication 15-T. For a year not yet on file the form starts from the latest earlier year's tables, so replace every amount. Enter each row's *at least* amount, *tentative amount to withhold* and *percentage* (12 for 12%), then choose **Save**. Every row is checked against the one above it: if a tentative amount doesn't match the row above plus that bracket's tax, the row is flagged with the amount expected and nothing is saved. Because the next row is checked against the mistyped one, a single typo usually flags two rows.

**Enter next year's Oklahoma tables.** Choose **Enter tables** in the *Oklahoma withholding* column. Enter the annual withholding allowance ($1,000 to date) and the *Single person* and *Married person* columns of Table 7, one row per line: *wages over*, *tax to withhold* and *percentage* (2.5 for 2.50%). Oklahoma changes how many brackets it has (seven in 2025, four in 2026), so the form has spare rows: fill rows from the top and leave the rest blank. A new year starts from the latest earlier year's table; replace every amount and clear rows the new table doesn't have. Rows are checked against each other in the same way as the federal tables.

**Correct a year.** Choose **Edit wage bases** or **Edit tables** (federal or Oklahoma) on the year, change the figures and save. Draft paychecks pick up the change when you choose **Recalculate**; approved and paid paychecks keep the figures they were calculated with.

**If a year is missing**, payroll still runs, using the latest earlier year's figures, and you are warned:
- **Tax Settings** shows a notice for the current year, and from October also for next year, for wage bases, federal tables and Oklahoma tables separately.
- A pay period that is open or in draft says, for example, *No 2027 wage bases on file* or *No 2027 Oklahoma withholding tables on file*, with a link to add them.
- The **Oklahoma SUTA** report marks the wage base as an earlier year's figure.

Every change is recorded in the audit log.

## 7. Managing employees

### Add an employee (preparers and admins)

1. Make sure the right company is active, then **Employees → New**.
2. Complete the form:

| Field | Notes |
|---|---|
| Company | Required. |
| First and last name | Required. |
| SSN | Optional here, stored encrypted. Enter with or without dashes. |
| Employment type | **Salaried**, **Hourly**, or **Part-time**. |
| Pay rate | Required. Annual salary for salaried; hourly rate otherwise. Hourly and part-time rates must be at least $7.25. |
| Pay frequency | Optional. Leave blank to use the company's. |
| Hire date | Used for new hire reporting. |
| Status | **Active**, **On leave**, or **Terminated**. |
| FLSA exempt | Tick if exempt from overtime. |
| Department, job title, contact, address | Optional. |
| Workers comp code | Only codes from the employee's own company are offered. |
| Exempt from workers comp | Tick for someone deliberately not covered (for example an officer who rejected coverage). Saving it clears any code, no workers comp premium is calculated for them, and they are left out of the missing-code warning. Untick and choose a code to cover them again. |
| Bank routing and account number | Optional, stored encrypted. |

3. Save. You land on the employee's profile.

The SSN and bank fields are encrypted in storage. Enter only what you need to.

### Tax elections

Add both after creating the employee. Until an election is on file, payroll withholds as the law requires for a missing form: federal as *Single* with no adjustments, Oklahoma as *single* with 0 allowances. The profile shows this in amber. Withholding is never skipped, so an employee who claims married status or allowances will be over-withheld until you add their forms.

- **Federal (W-4):** on the profile, **Add W-4**. Enter the effective date, filing status, whether the employee has multiple jobs, and the W-4 amounts (dependents, other income, deductions, extra withholding).
- **Oklahoma:** add the Oklahoma withholding election: effective date, filing status, allowances, and extra withholding. *Married* uses Oklahoma's married table; an employee who ticked "Married, but withhold at higher Single rate" on their OK-W-4 should be entered as *Single*. Oklahoma withholding is rounded to the whole dollar, as the Oklahoma Tax Commission requires.

When an employee files a new form, add a *new* election with the new effective date. The old ones stay as history, and the newest is used.

**Exempt employees.** If the employee claims exemption, tick **Exempt from withholding** on the W-4 form or **Exempt from Oklahoma withholding** on the Oklahoma form. No income tax of that kind is withheld, and the form's other amounts (multiple jobs, dependents, allowances, extra withholding) are ignored and saved as zero. Social Security and Medicare are still withheld. The profile card shows *Exempt*.

A federal exemption only lasts for the calendar year the W-4 was given. Unless the employee files a new W-4 by **February 15** of the next year, paychecks dated after that withhold as *Single* with no adjustments, and the profile shows an amber "Exemption expired" note. To renew, add a new W-4 with **Exempt from withholding** ticked. The Oklahoma exemption does not expire on its own; replace it by adding a new election.

### New hire reporting

Oklahoma requires new hires to be reported within 20 days. After you report someone, open their profile and choose **Mark as reported** next to *New Hire Reported*. The date is saved and they leave the New Hire report. The same button is on each row of the report. Only preparers and admins see it.

### Benefit enrollments

1. On the employee's profile, enroll them in a plan with an effective date. Optionally enter an **override amount** to replace the plan's standard employee contribution for this person.
2. To stop a deduction, end the enrollment on the profile and give an end date. Do not delete; ended enrollments stay as history.

### Garnishment orders

1. On the profile, open **Garnishments**, then **New Garnishment Order**.
2. Enter the type (child support, federal tax levy, state tax levy, creditor, student loan, bankruptcy, other), payee, case number, whether the amount is **fixed** or a **percent** of disposable earnings, the amount or percent, an optional **maximum total**, the effective date, and notes.
3. To stop one, choose **Deactivate** and give an end date.

Payroll applies active orders in legal priority order (child support first, then tax levies, student loans, creditors) and never withholds more than federal limits allow. The amount actually withheld can therefore be less than the order amount.

"Disposable earnings" is gross pay minus the taxes required by law (income tax, Social Security, Medicare). Health premiums, 401(k) contributions and other voluntary deductions are **not** subtracted, so they never reduce what an order can take. If a support order in your state allows health premiums to be deducted first, check with your accountant or attorney; that adjustment is not modeled.

### Time off (PTO and sick balances)

PTO and sick hours each have their own balance. A balance is tracked only for employees with a policy for it.

1. On the employee's profile, the **Time Off** card shows each tracked balance. Choose **Manage**.
2. Under **PTO** or **Sick**, choose **Set up policy** (or **Edit policy**) and enter:
   - **Accrual**: **Per pay period** (the same hours on every regular paycheck, e.g. 3.08 hours biweekly = 80 hours a year) or **Per hour worked** (a fraction of an hour for each hour worked, e.g. 0.0385 = 80 hours a year at 2,080 hours). Per hour worked counts regular, overtime and double time hours, not PTO, sick or holiday hours. Salaried employees count as working 2,080 hours a year.
   - **Maximum balance** (optional): accrual pauses while the balance is at this many hours.
   - **Year-end carryover limit** (optional): hours over this limit on December 31 are forfeited. The forfeit is recorded with the first pay run calculated in the new year, dated January 1. A new or changed limit applies from the next year-end, never to one already past.
3. Choose **Save policy**. To stop tracking, choose **Stop tracking** in the Accrual list and save; the history stays.
4. To enter an opening balance or correct one, choose **Adjust balance**, enter the hours (negative to take hours away), the date and a reason, and choose **Save adjustment**.

Hours accrue and are used through payroll:
- Enter hours taken in the **PTO** and **Sick** columns of the timesheet ([Stage 2](#stage-2-enter-timesheets-preparer)), for salaried employees too.
- **Calculate** works out each paycheck's hours accrued and used. They count toward the balance once the pay run is approved. Recalculating replaces them, and voiding the paycheck removes them.
- Off-cycle payments record hours used but accrue nothing.
- A balance can go negative. The timesheet shows each balance under the PTO and Sick boxes, in red when the hours entered are more than the balance, but it does not stop you.

The **History** list on the Time Off page shows every approved change: accruals, hours used, adjustments (with who made them) and year-end forfeits. Paychecks and pay stubs show the hours accrued, used and the balance after that paycheck.

### Editing, leaves, and terminations

- **Edit** changes any field. Pay rate changes apply to paychecks calculated afterwards.
- **On leave:** set the status to *On leave*. The employee is skipped in payroll runs until set back to *Active*.
- **Terminating:** set the status to *Terminated* and enter the termination date. A terminated employee gets a final paycheck automatically in the pay run that covers their last day, then drops out of later runs. See [Final paychecks](#final-paychecks).

## 8. Running payroll

The run has four stages, done by two roles: preparer (stages 1-3), approver (stage 4).

### Stage 1: Create the pay period (preparer)

1. **Pay Runs → New Pay Period**.
2. Choose the company; enter the **start date**, **end date**, **pay date**, and **frequency**. All three dates are required.
3. Save. The period is created as **open**.

### Stage 2: Enter timesheets (preparer)

Needed for **hourly and part-time** employees, and for salaried employees who took PTO or sick time. Salaried employees are paid automatically from their salary; their rows only have **PTO** and **Sick** boxes, which reduce their [time off balances](#time-off-pto-and-sick-balances) without changing their pay.

1. Open the pay period and choose **Timesheets**.
2. For each hourly or part-time employee enter hours in: regular, overtime, double time, PTO, sick, and holiday. Under the PTO and Sick boxes, **Bal** shows the employee's balance from approved pay runs if they have a time off policy; it turns red when the hours entered are more than the balance.
3. Each row saves on its own about a second after you change a value; a saved confirmation appears on the row. Only the row you edited is saved. On a phone the hour boxes are larger and bring up a number keypad, and the employee name stays in view while you swipe across the hour columns.

How hours turn into pay: regular, PTO, sick and holiday hours are paid at the hourly rate; overtime at 1.5 times; double time at 2 times. **Enter overtime hours yourself.** The system does not calculate overtime from a total.

An hourly employee with no timesheet gets $0.00 gross.

Timesheets can be changed while the period is *open* or *draft*, not after it is approved.

### Stage 3: Calculate the draft (preparer)

1. On the pay period page, choose **Calculate Draft**.
2. The system creates a draft paycheck for every **active** employee in that company. The period becomes **draft**.
3. **Review carefully.** You can open any paycheck to see its earnings, deductions, taxes, employer costs, and year-to-date totals.

The period page flags things worth a second look:

- **No workers comp code on file.** While the period is *open* or *draft*, active employees with no workers comp code are listed with a link to edit them. It is a warning only and never blocks calculating or approving, because some people (for example certain owners or officers) may legitimately be uncovered. Assign a code, or tick **Exempt from workers comp** on the employee for someone who is deliberately uncovered, and the warning clears. The employee profile shows the same note.
- **No Oklahoma withholding tables for the pay year.** Same as federal: the page says so, calculating uses the latest earlier year's, and an admin can add them under **Tax Settings**.
- **No federal withholding tables for the pay year.** If **Tax Settings** has no federal tables for the pay date's year, the page says so and calculating uses the latest earlier year's. Ask an admin to enter the year's tables, then **Recalculate**.
- **No wage bases for the pay year.** If **Tax Settings** has no figures for the pay date's year, the page says so and calculating uses the latest earlier year's. Ask an admin to add the year, then **Recalculate**.
- **Variance flag.** A draft whose gross pay is more than 20% different from the employee's previous approved or paid paycheck. Often a typo in hours, or a rate change.
- **Terminated employees needing a final paycheck.** See below.

Found a mistake? Fix the source (timesheet hours, employee rate, tax election, benefit enrollment), then choose **Recalculate**. Recalculating replaces the drafts. It is allowed any time before approval, except on off-cycle and bonus runs.

#### Final paychecks

When you **Calculate**, a terminated employee is included if their termination date falls between the period's start date and its pay date. The paycheck shows a **Final** badge on the period page.

- **Salaried:** the period salary is prorated by calendar days from the period start through the termination date. Ending on or after the period end pays the full period. Example: a $2,500.00 biweekly salary with a termination date on day 7 of 14 pays $1,250.00.
- **Hourly and part-time:** paid from the timesheet, as usual. Enter their hours before you calculate.
- Benefit deductions and garnishments still apply while their enrollments and orders are open. End any that should stop with the termination.

Before you calculate, the period page lists terminated employees as *included when you calculate*. Anyone terminated **before** the period start who never received a final paycheck is listed as *not included automatically*. To pay them, set their status back to *Active*, calculate, then set them to *Terminated* again (this pays a full period salary). Final pay only covers wages for the period. It does not include accrued time-off payouts or other extras; for those, void and use an off-cycle payment. Check with your accountant or payroll policy on final pay timing requirements.

### Stage 4: Approve and mark paid (approver)

1. Review the draft. Confirm totals and investigate any flags.
2. **Approve**. All draft paychecks become *approved* and the period becomes *approved*. The approval is recorded in the audit log with your name.
3. Issue payments outside the system (checks or bank transfers).
4. **Mark Paid**. Approved paychecks become *paid*, and the period becomes *paid*. If you issued printed checks, type the first check number in **First check # (optional)** beside the button. Approved paychecks are numbered consecutively from it, in the order they appear on the period. Leave it blank to skip numbering. A number already used by another non-voided paycheck in the same company stops the whole run with an error and changes nothing.

**Check numbers.** The period page has a **Check #** column. To set, change or clear one paycheck's number (for example a reprinted check), open the paycheck and use **Save Check #**. Only approved or paid paychecks can be numbered, and a number must be unique within the company. The number prints on the pay stub.

The system records payroll. It does not send money or file returns for you.

> Once approved, a period cannot be recalculated or edited. To correct one paycheck, void it (see [Voiding a paycheck](#10-voiding-a-paycheck)).

## 9. Off-cycle payments and bonuses

### Off-cycle payment

Use for a one-off payment of regular wages to one employee outside the regular schedule, such as a missed paycheck. For bonuses, use a [bonus run](#bonus-run) instead.

1. **Pay Runs → Off-Cycle**.
2. Choose the company, then the employee (the list shows that company's active employees), the **pay date**, and the **gross amount**. The gross amount must be greater than zero. Taxes use the employee's pay frequency, or the company's if the employee has none.
3. Save. The system creates a one-day pay period with a draft paycheck.
4. An approver approves and marks it paid, like any other run.

The gross amount you enter is what the paycheck pays. For **hourly and part-time** employees it is converted to hours at their pay rate. For **salaried** employees it replaces their per-period salary for this paycheck. For a salaried employee, the description you enter labels the earnings line, for example "Bonus". Hourly and part-time paychecks keep their normal "Regular Pay" line.

An off-cycle or bonus period has no **Timesheets** or **Recalculate** button: recalculating would redraft every employee in the company at regular pay. To change one, void the paycheck and create a new one.

### Bonus run

Use to pay a bonus (Christmas bonus, performance bonus and so on) to any number of employees at once.

1. Choose the company with the company switcher, then **Pay Runs → Bonus Run**.
2. Enter the **Pay Date** and a **Description**, for example "Christmas Bonus". It labels the earnings line on each pay stub.
3. Enter each employee's bonus in **Bonus (gross)**. Leave it blank to skip that employee.
4. Choose **Create Bonus Run**. The system creates one one-day pay period with a draft paycheck per employee.
5. An approver approves and marks it paid, like any other run.

A bonus paycheck is taxed and deducted differently from a regular one:
- **Federal income tax** is a flat 22% (the IRS supplemental rate), whatever the W-4 says. An employee with an exempt W-4 still has none withheld.
- **Oklahoma income tax** is the year's top rate from the Oklahoma tables under **Tax Settings** (4.75% in 2025, 4.5% in 2026), whatever the allowances. An exempt employee has none withheld.
- **The flat rates need withholding on regular pay.** Each flat rate is used only if that tax (federal or Oklahoma) was withheld from the employee's regular paychecks this year or last year. Off-cycle payments and earlier bonuses do not count. If none was, the bonus is added to the employee's latest regular paycheck this year and taxed as one regular paycheck, less the tax already withheld from that paycheck; with no regular paycheck this year, it is taxed as a regular paycheck on its own. Only paychecks run in this system are checked.
- **Social Security, Medicare, FUTA, SUTA and workers comp** are calculated as on any paycheck.
- **Benefit deductions** come out only for percent-of-pay plans, such as a 401k set as a percent (with any employer match). Fixed-dollar deductions, such as a health premium, are skipped: they are taken from regular paychecks.
- **Garnishments** come out only for orders set as a percent. Fixed-amount orders are skipped.
- No PTO or sick time accrues.

Each bonus must be under $1,000,000; the IRS mandatory 37% rate on supplemental wages over $1 million in a year is not calculated.

## 10. Voiding a paycheck

Approvers and admins can void a paycheck that is *draft* or *approved*.

1. Open the paycheck (from the pay period page).
2. Choose **Void**, enter a reason (required), and confirm.
3. The paycheck is marked voided, with the reason, your name, and the time.

Things to know:
- A **paid** paycheck cannot be voided.
- A voided paycheck is excluded from reports and from year-to-date totals, and its PTO and sick hours come off the balances.
- The period's status does not change, and no replacement paycheck is created. If the employee is still owed pay, create an off-cycle payment.

## 11. Pay stubs

Open any paycheck and choose **Pay Stub PDF**. The stub shows earnings, deductions, taxes, net pay, year-to-date totals, and, for employees with a time off policy, the PTO and sick hours accrued, used and the balance after this paycheck.

If the site reports the PDF service is unavailable (HTTP 503), a system library is missing on the server; tell your administrator. Everything else keeps working.

## 12. Reports

Open **Reports** and pick a report. Every report lets you choose the company; most also take a pay period or date range. Reports count only **approved** and **paid** paychecks: drafts (not yet approved) and voided paychecks are left out, so figures do not move while a run is still being reviewed. The one exception is the **Payroll register**, which lists every paycheck in the period you pick so you can review a draft before approving it.

| Report | What it shows | Use it for |
|---|---|---|
| **Payroll register** | Every paycheck in a pay period with gross, deductions, taxes, and net. | Reviewing a run; bookkeeping. |
| **Tax liability** | Federal, Oklahoma, FICA, FUTA and SUTA amounts. | Knowing what you owe and when. |
| **Quarterly 941** | Figures for the quarterly federal return. Choose year and quarter. | Preparing Form 941. |
| **Workers comp** | Wages by workers comp code with premium. Wages paid to employees with no code are grouped as *Unclassified* (the row names those employees), and wages paid to exempt employees get their own *EXEMPT* row with no premium. | Insurance audit. |
| **Oklahoma SUTA (OESC)** | Choose company, year and quarter. Per employee: total wages, excess wages, taxable wages and the SUTA contributions calculated, with totals, the company's rate and the taxable wage base for the chosen year. Approved and paid paychecks only. A **Print** button is provided. Only the last four SSN digits are shown. | Preparing your OESC quarterly contribution report. |
| **Oklahoma withholding** | Oklahoma tax withheld. | State withholding filings. |
| **W-2 export** | Downloads a CSV of per-employee W-2 box amounts. Box 1 (and Box 16) is gross pay less **pre-tax** deductions only: health and other cafeteria plans and traditional 401(k). Roth contributions, other post-tax deductions and garnishments do not reduce it. Box 3 (Social Security wages, capped at the wage base) and Box 5 (Medicare wages) are gross pay less cafeteria-plan items only, so 401(k) deferrals stay in them. SSN is not exported. **Box 12 code D** is the employee's traditional 401(k) deferrals for the year (the employer match is not included), and **Box 13 Retirement plan** is marked `X` when there are any. Roth 401(k) contributions (code AA) and other Box 12 codes are not exported; take them from the **Deductions and benefits** report. Paychecks calculated before 401(k) deferrals were flagged as such (October 2026) are not counted in Box 12, so check code D against that report for those months. | Year-end W-2 preparation. |
| **Deductions and benefits** | Benefit and deduction totals. | Reconciling with carriers. |
| **Client liabilities** | Amounts to send to garnishment payees, benefit carriers and retirement plans, once a payroll is approved. Voided paychecks drop out. Approvers get a **Mark Remitted** button on every payee row that still has an outstanding amount, with an optional check or ACH reference. | Knowing what to remit, and recording that you did. |
| **New hire reporting** | Hires from the last 20 days not yet marked as reported, with a **Mark as reported** button on each row. | Meeting new hire reporting deadlines. |

**Running across companies.** If you can access more than one company, six reports (register, tax liability, workers comp, deductions, client liabilities, new hires) can be run for *all* your companies at once. They show a subtotal per company and a grand total. The **941**, **Oklahoma SUTA**, **Oklahoma withholding**, and **W-2 export** must be run one company at a time, because each is filed under that company's own EIN.

## 13. Year-end checklist

1. Make sure every pay period for the year is **paid** and no drafts are left open.
2. Void anything wrong *before* running year-end reports.
3. Run the **Quarterly 941** and **Oklahoma SUTA** reports for each quarter and each company.
4. Run **Oklahoma withholding** for the year.
5. Run **W-2 export** for each company and compare against the payroll register.
6. Review employee addresses and SSNs on the profiles before producing W-2s.
7. Back up the database and the encryption key (see your administrator).
8. Admins: check **Tax Settings** has next year's wage bases and federal and Oklahoma withholding tables before the first payroll of January.
9. Approve every December pay run before calculating January's. Year-end time off forfeits are worked out when the first January pay run is calculated, from the balances approved by then.

Confirm figures against the official IRS and Oklahoma Tax Commission instructions before filing.

## 14. Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| Cannot sign in | Check username and password. After five failures wait a few minutes. Ask an admin to reset your password. |
| Screens are empty or a company is missing | You have no company assigned, or the wrong company is active. Use the company switcher, or ask an admin. |
| A button is missing | Your role does not allow it. See [Roles](#2-roles-and-what-you-can-do). |
| "Not found" on a page you were using | Your access to that company was removed, or the record is in a company you cannot access. |
| Employee is missing from the payroll run | Status is not *Active*, or the employee belongs to a different company than the pay period. |
| Employee paid $0.00 | Hourly or part-time with no timesheet for the period. |
| Withholding looks too high | No W-4 or Oklahoma election on the employee, so the single / 0-allowance default was used, or the employee's federal exemption expired on February 15. Add the forms and recalculate. |
| No income tax withheld at all | The W-4 or Oklahoma election is marked *Exempt*. Check the profile. |
| Federal income tax is zero | Wages for the period are below the withholding threshold for the employee's filing status and W-4 amounts. This is expected. |
| Cannot calculate or edit hours | The period is already approved or paid. |
| Time off balance did not change after Calculate | Hours count once the pay run is approved. The employee also needs a policy for that type of time off. |
| No time off was accrued on a paycheck | The balance is at its maximum, the payment is off-cycle or a bonus, or (per hour worked) no regular, overtime or double time hours were entered. |
| "Cannot approve" or "Cannot mark paid" | The period is not in the expected earlier status. Calculate first, then approve, then mark paid. |
| Cannot void a paycheck | It is already paid or already voided. |
| Benefit not deducted | The plan is inactive, the enrollment has ended, or the contribution amount is zero. |
| Garnishment is less than the order | Legal limits on disposable earnings cap it. |
| Bonus withholding is not 22% | No federal (or Oklahoma) tax was withheld from the employee's regular paychecks in this system this year or last, so the bonus was taxed with their latest regular paycheck instead. See [Bonus run](#bonus-run). |
| Health premium or fixed garnishment missing on a bonus | Bonus runs take only percent-of-pay deductions and percent garnishments. See [Bonus run](#bonus-run). |
| Cannot demote or deactivate an admin | You are trying to change the last active admin. Make another admin first. |
| Workers comp code will not save | The code belongs to a different company than the employee. |
| PDF pay stub fails | Server is missing a PDF library. Tell your administrator. |

## 15. Things to know

- **Remittances are marked per payee, not per payment.** **Mark Remitted** marks everything outstanding for that payee, company and year in one go. There is no undo and no partial amount; ask an administrator if one was marked by mistake.
- **Employer insurance premiums** are not modeled. Client liabilities include the employee's deduction and any employer match, not a company-paid premium share.
- **Test data only** on the Docker test deployment: it runs over plain HTTP, so anything typed (including your password) can be read on the network. Use fake SSNs and bank numbers there.
- **Backups.** The database and the encryption key must both be backed up. Without the key, stored Social Security and bank numbers cannot be read.
- **Time off payout** on termination is not calculated. If your policy pays out unused PTO, add it to the final paycheck as an off-cycle payment and enter a negative adjustment for the hours.
- **Audit log.** The system records who created or changed employees, pay periods, approvals, voids, user roles, company assignments, and time off policies and adjustments. It is stored in the database and is not yet shown on any screen.
