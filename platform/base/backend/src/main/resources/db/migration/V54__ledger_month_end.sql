-- What a lot held at the end of a closed month belongs to the quantity ledger, not to the period locks: the ledger keeps it when it hears
-- that a month of one of its screens' lock groups closed.
ALTER TABLE period_lock_balances RENAME TO ledger_month_end;
