# Installation result

- Repository: https://github.com/antropos17/reviews-test (public)
- Default branch: https://github.com/antropos17/reviews-test/tree/main
- Data branch: https://github.com/antropos17/reviews-test/tree/reviews
- Initial manual run: https://github.com/antropos17/reviews-test/actions/runs/40486088686
- Issue creation run: https://github.com/antropos17/reviews-test/actions/runs/40486267319
- Rating edit run: https://github.com/antropos17/reviews-test/actions/runs/40486334127
- Reply run: https://github.com/antropos17/reviews-test/actions/runs/40486374755
- Hide run: https://github.com/antropos17/reviews-test/actions/runs/40486422950
- Restore run: https://github.com/antropos17/reviews-test/actions/runs/40486463868
- Test issue: https://github.com/antropos17/reviews-test/issues/1
- Cards: https://github.com/antropos17/reviews-test/blob/reviews/card-light.svg and https://github.com/antropos17/reviews-test/blob/reviews/card-dark.svg

The initial snapshot contained zero votes. The issue event recorded one rating of 4, and editing the same issue changed the average to 5 with one vote. A maintainer reply appeared in JSON and SVG. The hidden label removed the vote, and removing the label restored it. All listed runs succeeded; 22 local parsing and aggregation tests passed. The five rating links render, and the fourth opens an issue with rating 4 prefilled. Both SVG themes rendered at the verified data commit. GitHub image caching showed an older card in the main README during verification; updates may be delayed.
