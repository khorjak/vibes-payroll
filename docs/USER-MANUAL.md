# Payroll User Manual

A guide for the people who use the Payroll application day to day. For diagrams of how the pieces fit together, see [PROCESS-FLOW.md](PROCESS-FLOW.md).

Button and menu names below match the screens as closely as possible. If a button is missing for you, your role probably does not allow that action (see [Roles](#2-roles-and-what-you-can-do)).

## Contents

1. [Getting started](#1-getting-started)
2. [Roles and what you can do](#2-roles-and-what-you-can-do)
3. [Finding your way around](#3-finding-your-way-around)
4. [Setting up a company (admins)](#4-setting-up-a-company-admins)
5. [Managing users (admins)](#5-managing-users-admins)
6. [Managing employees](#6-managing-employees)
7. [Running payroll](#7-running-payroll)
8. [Off-cycle payments](#8-off-cycle-payments)
9. [Voiding a paycheck](#9-voiding-a-paycheck)
10. [Pay stubs](#10-pay-stubs)
11. [Reports](#11-reports)
12. [Year-end checklist](#12-year-end-checklist)
13. [Troubleshooting](#13-troubleshooting)
14. [Things to know](#14-things-to-know)

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
| **Preparer** | Payroll clerks | Everything read-only can, plus add and edit employees, tax elections, benefit enrollments and garnishments; create pay periods; enter timesheets; calculate the draft payroll; create off-cycle payments. |
| **Approver** | Payroll managers | Everything read-only can, plus approve a payroll run, mark it paid, and void a paycheck. |
| **Admin** | Whoever runs the system | Everything, plus company, benefit plan and workers comp setup, and user management. |

Preparing and approving are separate on purpose, so one person cannot both build and release a payroll. Give a person both roles only if you accept that. An admin can do both.

**Company access** is separate from role. A non-admin user only sees the companies an admin assigned to them. If you see nothing at all, you have not been assigned a company; ask an admin. Admins see every company.

## 3. Finding your way around

The left navigation has: **Dashboard**, **Employees**, **Companies**, **Users** (admins only), **Payroll**, and **Reports**.

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
- An employee's **override** (set when enrolling them) uses the same unit as the plan: dollars for a fixed plan, a percent (0 to 100) for a percent plan. An override of 0 means no deduction for that employee.

## 5. Managing users (admins)

**Users** lists everyone with their role, active status, and company access.

**Add a user.** **Users → New**: enter a username, an initial password (8+ characters), a role, and tick the companies they may access. Admin accounts need no company ticks.

**Edit a user.** Change role, active status, and company access. Removing a company takes effect immediately, on the person's next click.

**Reset a password.** Choose **Reset Password** on the user, then enter a new password (8+ characters). Tell the person through a private channel.

**Safeguards.**
- You cannot demote or deactivate the last active admin.
- Reactivating a deactivated non-admin does **not** restore their company access. Re-assign companies yourself; the list shows an amber "None" for such accounts. This is deliberate, because accounts can view Social Security and bank data.

## 6. Managing employees

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
| Bank routing and account number | Optional, stored encrypted. |

3. Save. You land on the employee's profile.

The SSN and bank fields are encrypted in storage. Enter only what you need to.

### Tax elections

An employee's paycheck cannot withhold correctly without these. Add both after creating the employee.

- **Federal (W-4):** on the profile, **Add W-4**. Enter the effective date, filing status, whether the employee has multiple jobs, and the W-4 amounts (dependents, other income, deductions, extra withholding).
- **Oklahoma:** add the Oklahoma withholding election: effective date, filing status, allowances, and extra withholding.

When an employee files a new form, add a *new* election with the new effective date. The old ones stay as history, and the newest is used.

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

### Editing, leaves, and terminations

- **Edit** changes any field. Pay rate changes apply to paychecks calculated afterwards.
- **On leave:** set the status to *On leave*. The employee is skipped in payroll runs until set back to *Active*.
- **Terminating:** set the status to *Terminated* and enter the termination date. Terminated employees are **not** included in payroll runs. If a final paycheck is owed, see [Final paychecks](#final-paychecks).

## 7. Running payroll

The run has four stages, done by two roles: preparer (stages 1-3), approver (stage 4).

### Stage 1: Create the pay period (preparer)

1. **Payroll → New Pay Period**.
2. Choose the company; enter the **start date**, **end date**, **pay date**, and **frequency**. All three dates are required.
3. Save. The period is created as **open**.

### Stage 2: Enter timesheets (preparer)

Only needed for **hourly and part-time** employees. Salaried employees are paid automatically from their salary, and any hours entered for them are ignored.

1. Open the pay period and choose **Timesheets**.
2. For each employee enter hours in: regular, overtime, double time, PTO, sick, and holiday.
3. Each row saves on its own; a saved confirmation appears on the row.

How hours turn into pay: regular, PTO, sick and holiday hours are paid at the hourly rate; overtime at 1.5 times; double time at 2 times. **Enter overtime hours yourself.** The system does not calculate overtime from a total.

An hourly employee with no timesheet gets $0.00 gross.

Timesheets can be changed while the period is *open* or *draft*, not after it is approved.

### Stage 3: Calculate the draft (preparer)

1. On the pay period page, choose **Calculate Draft**.
2. The system creates a draft paycheck for every **active** employee in that company. The period becomes **draft**.
3. **Review carefully.** You can open any paycheck to see its earnings, deductions, taxes, employer costs, and year-to-date totals.

The period page flags things worth a second look:

- **Variance flag.** A draft whose gross pay is more than 20% different from the employee's previous approved or paid paycheck. Often a typo in hours, or a rate change.
- **Terminated employees needing a final paycheck.** See below.

Found a mistake? Fix the source (timesheet hours, employee rate, tax election, benefit enrollment), then choose **Recalculate**. Recalculating replaces the drafts. It is allowed any time before approval.

#### Final paychecks

A terminated employee is not drafted automatically. If someone is owed a final paycheck, the period page lists them as needing one. Set their status back to *Active* for the calculation, calculate, then set them to *Terminated* again afterwards. Check with your accountant or payroll policy on final pay timing requirements.

### Stage 4: Approve and mark paid (approver)

1. Review the draft. Confirm totals and investigate any flags.
2. **Approve**. All draft paychecks become *approved* and the period becomes *approved*. The approval is recorded in the audit log with your name.
3. Issue payments outside the system (checks or bank transfers).
4. **Mark Paid**. Approved paychecks become *paid*, and the period becomes *paid*.

The system records payroll. It does not send money or file returns for you.

> Once approved, a period cannot be recalculated or edited. To correct one paycheck, void it (see [Voiding a paycheck](#9-voiding-a-paycheck)).

## 8. Off-cycle payments

Use for a one-off payment to one employee outside the regular schedule.

1. **Payroll → Off-Cycle Payroll**.
2. Choose the company, then the employee (the list shows that company's active employees), the **pay date**, and the **gross amount**. The gross amount must be greater than zero.
3. Save. The system creates a one-day pay period with a draft paycheck.
4. An approver approves and marks it paid, like any other run.

The gross amount you enter is what the paycheck pays. For **hourly and part-time** employees it is converted to hours at their pay rate. For **salaried** employees it replaces their per-period salary for this paycheck. For a salaried employee, the description you enter labels the earnings line, for example "Bonus". Hourly and part-time paychecks keep their normal "Regular Pay" line.

Do not choose **Recalculate** on an off-cycle period. It redrafts every active employee in the company and replaces a salaried employee's entered amount with their normal salary. To change an off-cycle payment, void the paycheck and create a new one.

## 9. Voiding a paycheck

Approvers and admins can void a paycheck that is *draft* or *approved*.

1. Open the paycheck (from the pay period page).
2. Choose **Void**, enter a reason (required), and confirm.
3. The paycheck is marked voided, with the reason, your name, and the time.

Things to know:
- A **paid** paycheck cannot be voided.
- A voided paycheck is excluded from reports and from year-to-date totals.
- The period's status does not change, and no replacement paycheck is created. If the employee is still owed pay, create an off-cycle payment.

## 10. Pay stubs

Open any paycheck and choose **Pay Stub PDF**. The stub shows earnings, deductions, taxes, net pay, and year-to-date totals.

If the site reports the PDF service is unavailable (HTTP 503), a system library is missing on the server; tell your administrator. Everything else keeps working.

## 11. Reports

Open **Reports** and pick a report. Every report lets you choose the company; most also take a pay period or date range. Voided paychecks are always left out.

| Report | What it shows | Use it for |
|---|---|---|
| **Payroll register** | Every paycheck in a pay period with gross, deductions, taxes, and net. | Reviewing a run; bookkeeping. |
| **Tax liability** | Federal, Oklahoma, FICA, FUTA and SUTA amounts. | Knowing what you owe and when. |
| **Quarterly 941** | Figures for the quarterly federal return. Choose year and quarter. | Preparing Form 941. |
| **Workers comp** | Wages by workers comp code with premium. | Insurance audit. |
| **Oklahoma withholding** | Oklahoma tax withheld. | State withholding filings. |
| **W-2 export** | Downloads a CSV of per-employee W-2 box amounts. | Year-end W-2 preparation. |
| **Deductions and benefits** | Benefit and deduction totals. | Reconciling with carriers. |
| **Client liabilities** | Amounts to send to garnishment payees, benefit carriers and retirement plans, once a payroll is approved. Voided paychecks drop out. | Knowing what to remit. |
| **New hire reporting** | Hires from the last 20 days not yet marked as reported, with a **Mark as reported** button on each row. | Meeting new hire reporting deadlines. |

**Running across companies.** If you can access more than one company, six reports (register, tax liability, workers comp, deductions, client liabilities, new hires) can be run for *all* your companies at once. They show a subtotal per company and a grand total. The **941**, **Oklahoma withholding**, and **W-2 export** must be run one company at a time, because each is filed under that company's own EIN.

## 12. Year-end checklist

1. Make sure every pay period for the year is **paid** and no drafts are left open.
2. Void anything wrong *before* running year-end reports.
3. Run the **Quarterly 941** for each quarter and each company.
4. Run **Oklahoma withholding** for the year.
5. Run **W-2 export** for each company and compare against the payroll register.
6. Review employee addresses and SSNs on the profiles before producing W-2s.
7. Back up the database and the encryption key (see your administrator).

Confirm figures against the official IRS and Oklahoma Tax Commission instructions before filing.

## 13. Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| Cannot sign in | Check username and password. After five failures wait a few minutes. Ask an admin to reset your password. |
| Screens are empty or a company is missing | You have no company assigned, or the wrong company is active. Use the company switcher, or ask an admin. |
| A button is missing | Your role does not allow it. See [Roles](#2-roles-and-what-you-can-do). |
| "Not found" on a page you were using | Your access to that company was removed, or the record is in a company you cannot access. |
| Employee is missing from the payroll run | Status is not *Active*, or the employee belongs to a different company than the pay period. |
| Employee paid $0.00 | Hourly or part-time with no timesheet for the period. |
| Withholding looks wrong or is zero | No W-4 or Oklahoma election on the employee. Add them and recalculate. |
| Cannot calculate or edit hours | The period is already approved or paid. |
| "Cannot approve" or "Cannot mark paid" | The period is not in the expected earlier status. Calculate first, then approve, then mark paid. |
| Cannot void a paycheck | It is already paid or already voided. |
| Benefit not deducted | The plan is inactive, the enrollment has ended, or the contribution amount is zero. |
| Garnishment is less than the order | Legal limits on disposable earnings cap it. |
| Cannot demote or deactivate an admin | You are trying to change the last active admin. Make another admin first. |
| Workers comp code will not save | The code belongs to a different company than the employee. |
| PDF pay stub fails | Server is missing a PDF library. Tell your administrator. |

## 14. Things to know

- **Remittances are not tracked yet.** The Client liabilities report shows what is owed, but there is no screen to record that a payment was sent, so its remitted column stays at $0.00.
- **Employer insurance premiums** are not modeled. Client liabilities include the employee's deduction and any employer match, not a company-paid premium share.
- **Test data only** on the Docker test deployment: it runs over plain HTTP, so anything typed (including your password) can be read on the network. Use fake SSNs and bank numbers there.
- **Backups.** The database and the encryption key must both be backed up. Without the key, stored Social Security and bank numbers cannot be read.
- **Audit log.** The system records who created or changed employees, pay periods, approvals, voids, user roles, and company assignments. It is stored in the database and is not yet shown on any screen.
