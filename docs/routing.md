# Model and effort routing

The router minimizes expected compute while retaining conservative quality gates. It makes one fresh decision per subtask and never changes the parent chat model.

## Discovery

`jev_route.py` starts `codex app-server --stdio`, performs `initialize`, sends `initialized`, and requests `model/list`. The process is short-lived, has a three-second discovery timeout, and does not receive `TYPESAFE_API_KEY` in its environment.

The catalog keeps visible general-purpose IDs matching `gpt-<numeric-family>-<role>`, records the reasoning efforts each model reports, and selects the newest two numeric families. Hidden and specialty models are excluded. If only one usable family exists, routing stays within it. Pagination, malformed output, timeout, or process failure returns `route=inherit`.

## Jev decision

Jev evaluates five typed values:

- least sufficient tier: `fast`, `balanced`, or `deep`;
- least sufficient reasoning effort;
- probability that an underpowered model would cause material harm;
- probability that the previous GPT family is insufficient;
- probability that current-family Sol is insufficient even at high effort.

Tier confidence below `0.30` inherits. Downgrading below the known parent tier requires confidence of at least `0.60`. When the current parent model is unknown, only a `deep` decision can select an explicit model.

## Roles and families

| Tier | Previous family when sufficient | Current family fallback | Calibrated effort range |
|---|---|---|---|
| `fast` | Luna | Luna, then Sol | `low` |
| `balanced` | Terra, then Sol | Sol | `low` to `medium` |
| `deep` | Sol | Sol | `high` to `max` |

The previous family is eligible when its insufficiency probability is at most `0.50` for `fast` and `balanced`, or at most `0.30` for `deep`. The current family is otherwise used.

Astra is reserved for `deep` tasks when the probability that current-family Sol is insufficient is greater than `0.70`. High consequence alone does not select Astra; risk above `0.70` raises effort to at least `high` without changing model or family.

## Effort

Selectable efforts are `low`, `medium`, `high`, `xhigh`, and `max`. `ultra` is intentionally excluded. Jev's effort score is bounded by the calibrated tier range above; risk above `0.70` can still raise any tier to at least `high`. If the resulting effort is unavailable, the router chooses the next supported higher effort, or the highest supported lower effort when none is higher.

## Fallbacks

The router returns `route=inherit` without `model` or `reasoning_effort` when:

- `TYPESAFE_API_KEY` is missing;
- `JEV_ROUTER_DISABLED=1`;
- the task contains secret-like input or exceeds 20,000 characters;
- App Server discovery fails or produces an incomplete catalog;
- TypeSafe times out, rejects the request, or returns invalid data;
- confidence or parent-model safety rules reject an explicit downgrade;
- no compatible model/effort pair exists.

Inheritance is successful safe behavior. It does not cancel useful delegation. When Codex rejects an explicit pair, the policy retries once by inheritance without another Jev request.

## Token-use objective

The policy prefers the lightest pair judged reliable, including the previous available GPT family. It does not claim a fixed percentage saving: completion length, retries, and model behavior determine actual token use.
