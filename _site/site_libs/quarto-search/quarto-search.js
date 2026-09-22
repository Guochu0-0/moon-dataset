const kQueryArg = "q";
const kResultsArg = "show-results";

// If items don't provide a URL, then both the navigator and the onSelect
// function aren't called (and therefore, the default implementation is used)
//
// We're using this sentinel URL to signal to those handlers that this
// item is a more item (along with the type) and can be handled appropriately
const kItemTypeMoreHref = "0767FDFD-0422-4E5A-BC8A-3BE11E5BBA05";

// Capture search params and clean ?q= from URL at module load time, before
// any DOMContentLoaded handlers run. quarto-nav.js resolves all <a> hrefs
// against window.location during DOMContentLoaded — if ?q= is still present,
// every link on the page gets the query param baked into its href.
const currentUrl = new URL(window.location);
const kQuery = currentUrl.searchParams.get(kQueryArg);
if (kQuery) {
  const replacementUrl = new URL(window.location);
  replacementUrl.searchParams.delete(kQueryArg);
  window.history.replaceState({}, "", replacementUrl);
}

window.document.addEventListener("DOMContentLoaded", function (_event) {
  // Ensure that search is available on this page. If it isn't,
  // should return early and not do anything
  var searchEl = window.document.getElementById("quarto-search");
  if (!searchEl) return;

  const { autocomplete } = window["@algolia/autocomplete-js"];

  let quartoSearchOptions = {};
  let language = {};
  const searchOptionEl = window.document.getElementById(
    "quarto-search-options"
  );
  if (searchOptionEl) {
    const jsonStr = searchOptionEl.textContent;
    quartoSearchOptions = JSON.parse(jsonStr);
    language = quartoSearchOptions.language;
  }

  // note the search mode
  if (quartoSearchOptions.type === "overlay") {
    searchEl.classList.add("type-overlay");
  } else {
    searchEl.classList.add("type-textbox");
  }

  // Used to determine highlighting behavior for this page
  // A `q` query param is expected when the user follows a search
  // to this page
  const query = kQuery;
  const showSearchResults = currentUrl.searchParams.get(kResultsArg);
  const mainEl = window.document.querySelector("main");

  // highlight matches on the page
  if (query && mainEl) {
    highlight(query, mainEl);

    // Activate tabs on pageshow — after tabsets.js restores localStorage state.
    // tabsets.js registers its pageshow handler during module execution (before
    // DOMContentLoaded). By registering ours during DOMContentLoaded, listener
    // ordering guarantees we run after tabsets.js — so search activation wins.
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) {
        for (const mark of mainEl.querySelectorAll("mark")) {
          openAllTabsetsContainingEl(mark);
        }
        // Only scroll to first match when there's no hash fragment.
        // With a hash, the browser already scrolled to the target section.
        if (!currentUrl.hash) {
          requestAnimationFrame(() => scrollToFirstVisibleMatch(mainEl));
        }
      }
    }, { once: true });
  }

  // function to clear highlighting on the page when the search query changes
  // (e.g. if the user edits the query or clears it)
  let highlighting = true;
  const resetHighlighting = (searchTerm) => {
    if (mainEl && highlighting && query && searchTerm !== query) {
      clearHighlight(query, mainEl);
      highlighting = false;
    }
  };

  // Responsively switch to overlay mode if the search is present on the navbar
  // Note that switching the sidebar to overlay mode requires more coordinate (not just
  // the media query since we generate different HTML for sidebar overlays than we do
  // for sidebar input UI)
  const detachedMediaQuery =
    quartoSearchOptions.type === "overlay" ? "all" : "(max-width: 991px)";

  // If configured, include the analytics client to send insights
  const plugins = configurePlugins(quartoSearchOptions);

  let lastState = null;
  const { setIsOpen, setQuery, setCollections } = autocomplete({
    container: searchEl,
    detachedMediaQuery: detachedMediaQuery,
    defaultActiveItemId: 0,
    panelContainer: "#quarto-search-results",
    panelPlacement: quartoSearchOptions["panel-placement"],
    debug: false,
    openOnFocus: true,
    plugins,
    classNames: {
      form: "d-flex",
    },
    placeholder: language["search-text-placeholder"],
    translations: {
      clearButtonTitle: language["search-clear-button-title"],
      detachedCancelButtonText: language["search-detached-cancel-button-title"],
      submitButtonTitle: language["search-submit-button-title"],
    },
    initialState: {
      query,
    },
    getItemUrl({ item }) {
      return item.href;
    },
    onStateChange({ state }) {
      // If this is a file URL, note that

      // Perhaps reset highlighting
      resetHighlighting(state.query);

      // If the panel just opened, ensure the panel is positioned properly
      if (state.isOpen) {
        if (lastState && !lastState.isOpen) {
          setTimeout(() => {
            positionPanel(quartoSearchOptions["panel-placement"]);
          }, 150);
        }
      }

      // Perhaps show the copy link
      showCopyLink(state.query, quartoSearchOptions);

      lastState = state;
    },
    reshape({ sources, state }) {
      return sources.map((source) => {
        try {
          const items = source.getItems();

          // Validate the items
          validateItems(items);

          // group the items by document
          const groupedItems = new Map();
          items.forEach((item) => {
            const hrefParts = item.href.split("#");
            const baseHref = hrefParts[0];
            const isDocumentItem = hrefParts.length === 1;

            const items = groupedItems.get(baseHref);
            if (!items) {
              groupedItems.set(baseHref, [item]);
            } else {
              // If the href for this item matches the document
              // exactly, place this item first as it is the item that represents
              // the document itself
              if (isDocumentItem) {
                items.unshift(item);
              } else {
                items.push(item);
              }
              groupedItems.set(baseHref, items);
            }
          });

          const reshapedItems = [];
          let count = 1;
          for (const [_key, value] of groupedItems) {
            const firstItem = value[0];
            reshapedItems.push({
              ...firstItem,
              type: kItemTypeDoc,
            });

            const collapseMatches = quartoSearchOptions["collapse-after"];
            const collapseCount =
              typeof collapseMatches === "number" ? collapseMatches : 1;

            if (value.length > 1) {
              const target = `search-more-${count}`;
              const isExpanded =
                state.context.expanded &&
                state.context.expanded.includes(target);

              const remainingCount = value.length - collapseCount;

              for (let i = 1; i < value.length; i++) {
                if (collapseMatches && i === collapseCount) {
                  reshapedItems.push({
                    target,
                    title: isExpanded
                      ? language["search-hide-matches-text"]
                      : remainingCount === 1
                        ? `${remainingCount} ${language["search-more-match-text"]}`
                        : `${remainingCount} ${language["search-more-matches-text"]}`,
                    type: kItemTypeMore,
                    href: kItemTypeMoreHref,
                  });
                }

                if (isExpanded || !collapseMatches || i < collapseCount) {
                  reshapedItems.push({
                    ...value[i],
                    type: kItemTypeItem,
                    target,
                  });
                }
              }
            }
            count += 1;
          }

          return {
            ...source,
            getItems() {
              return reshapedItems;
            },
          };
        } catch (error) {
          // Some form of error occurred
          return {
            ...source,
            getItems() {
              return [
                {
                  title: error.name || "An Error Occurred While Searching",
                  text:
                    error.message ||
                    "An unknown error occurred while attempting to perform the requested search.",
                  type: kItemTypeError,
                },
              ];
            },
          };
        }
      });
    },
    navigator: {
      navigate({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          window.location.assign(itemUrl);
        }
      },
      navigateNewTab({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          const windowReference = window.open(itemUrl, "_blank", "noopener");
          if (windowReference) {
            windowReference.focus();
          }
        }
      },
      navigateNewWindow({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          window.open(itemUrl, "_blank", "noopener");
        }
      },
    },
    getSources({ state, setContext, setActiveItemId, refresh }) {
      return [
        {
          sourceId: "documents",
          getItemUrl({ item }) {
            if (item.href) {
              return offsetURL(item.href);
            } else {
              return undefined;
            }
          },
          onSelect({
            item,
            state,
            setContext,
            setIsOpen,
            setActiveItemId,
            refresh,
          }) {
            if (item.type === kItemTypeMore) {
              toggleExpanded(item, state, setContext, setActiveItemId, refresh);

              // Toggle more
              setIsOpen(true);
            }
          },
          getItems({ query }) {
            if (query === null || query === "") {
              return [];
            }

            const limit = quartoSearchOptions.limit;
            if (quartoSearchOptions.algolia) {
              return algoliaSearch(query, limit, quartoSearchOptions.algolia);
            } else {
              // Fuse search options
              const fuseSearchOptions = {
                isCaseSensitive: false,
                shouldSort: true,
                minMatchCharLength: 2,
                limit: limit,
              };

              return readSearchData().then(function (fuse) {
                return fuseSearch(query, fuse, fuseSearchOptions);
              });
            }
          },
          templates: {
            noResults({ createElement }) {
              const hasQuery = lastState.query;

              return createElement(
                "div",
                {
                  class: `quarto-search-no-results${hasQuery ? "" : " no-query"
                    }`,
                },
                language["search-no-results-text"]
              );
            },
            header({ items, createElement }) {
              // count the documents
              const count = items.filter((item) => {
                return item.type === kItemTypeDoc;
              }).length;

              if (count > 0) {
                return createElement(
                  "div",
                  { class: "search-result-header" },
                  `${count} ${language["search-matching-documents-text"]}`
                );
              } else {
                return createElement(
                  "div",
                  { class: "search-result-header-no-results" },
                  ``
                );
              }
            },
            footer({ _items, createElement }) {
              if (
                quartoSearchOptions.algolia &&
                quartoSearchOptions.algolia["show-logo"]
              ) {
                const libDir = quartoSearchOptions.algolia["libDir"];
                const logo = createElement("img", {
                  src: offsetURL(
                    `${libDir}/quarto-search/search-by-algolia.svg`
                  ),
                  class: "algolia-search-logo",
                });
                return createElement(
                  "a",
                  { href: "http://www.algolia.com/" },
                  logo
                );
              }
            },

            item({ item, createElement }) {
              if (item.text && item.href && !item.href.includes('?q=')) {
                const [main, hash] = item.href.split('#')
                const hashAppend = hash ? '#' + hash : ''
                item.href = main + '?q=' + encodeURIComponent(state.query) + hashAppend
              }

              return renderItem(
                item,
                createElement,
                state,
                setActiveItemId,
                setContext,
                refresh,
                quartoSearchOptions
              );
            },
          },
        },
      ];
    },
  });

  window.quartoOpenSearch = () => {
    setIsOpen(false);
    setIsOpen(true);
    focusSearchInput();
  };

  document.addEventListener("keyup", (event) => {
    const { key } = event;
    const kbds = quartoSearchOptions["keyboard-shortcut"];
    const focusedEl = document.activeElement;

    const isFormElFocused = [
      "input",
      "select",
      "textarea",
      "button",
      "option",
    ].find((tag) => {
      return focusedEl.tagName.toLowerCase() === tag;
    });

    if (
      kbds &&
      kbds.includes(key) &&
      !isFormElFocused &&
      !document.activeElement.isContentEditable
    ) {
      event.preventDefault();
      window.quartoOpenSearch();
    }
  });

  // Remove the labeleledby attribute since it is pointing
  // to a non-existent label
  if (quartoSearchOptions.type === "overlay") {
    const inputEl = window.document.querySelector(
      "#quarto-search .aa-Autocomplete"
    );
    if (inputEl) {
      inputEl.removeAttribute("aria-labelledby");
    }
  }

  function throttle(func, wait) {
    let waiting = false;
    return function () {
      if (!waiting) {
        func.apply(this, arguments);
        waiting = true;
        setTimeout(function () {
          waiting = false;
        }, wait);
      }
    };
  }

  // If the main document scrolls dismiss the search results
  // (otherwise, since they're floating in the document they can scroll with the document)
  window.document.body.onscroll = throttle(() => {
    // Only do this if we're not detached
    // Bug #7117
    // This will happen when the keyboard is shown on ios (resulting in a scroll)
    // which then closed the search UI
    if (!window.matchMedia(detachedMediaQuery).matches) {
      setIsOpen(false);
    }
  }, 50);

  if (showSearchResults) {
    setIsOpen(true);
    focusSearchInput();
  }
});

function configurePlugins(quartoSearchOptions) {
  const autocompletePlugins = [];
  const algoliaOptions = quartoSearchOptions.algolia;
  if (
    algoliaOptions &&
    algoliaOptions["analytics-events"] &&
    algoliaOptions["search-only-api-key"] &&
    algoliaOptions["application-id"]
  ) {
    const apiKey = algoliaOptions["search-only-api-key"];
    const appId = algoliaOptions["application-id"];

    // Aloglia insights may not be loaded because they require cookie consent
    // Use deferred loading so events will start being recorded when/if consent
    // is granted.
    const algoliaInsightsDeferredPlugin = deferredLoadPlugin(() => {
      if (
        window.aa &&
        window["@algolia/autocomplete-plugin-algolia-insights"]
      ) {
        // Check if cookie consent is enabled from search options
        const cookieConsentEnabled = algoliaOptions["cookie-consent-enabled"] || false;

        // Generate random session token only when cookies are disabled
        const userToken = cookieConsentEnabled ? undefined : Array.from(Array(20), () =>
          Math.floor(Math.random() * 36).toString(36)
        ).join("");

        window.aa("init", {
          appId,
          apiKey,
          useCookie: cookieConsentEnabled,
          userToken: userToken,
        });

        const { createAlgoliaInsightsPlugin } =
          window["@algolia/autocomplete-plugin-algolia-insights"];
        // Register the insights client
        const algoliaInsightsPlugin = createAlgoliaInsightsPlugin({
          insightsClient: window.aa,
          onItemsChange({ insights, insightsEvents }) {
            const events = insightsEvents.flatMap((event) => {
              // This API limits the number of items per event to 20
              const chunkSize = 20;
              const itemChunks = [];
              const eventItems = event.items;
              for (let i = 0; i < eventItems.length; i += chunkSize) {
                itemChunks.push(eventItems.slice(i, i + chunkSize));
              }
              // Split the items into multiple events that can be sent
              const events = itemChunks.map((items) => {
                return {
                  ...event,
                  items,
                };
              });
              return events;
            });

            for (const event of events) {
              insights.viewedObjectIDs(event);
            }
          },
        });
        return algoliaInsightsPlugin;
      }
    });

    // Add the plugin
    autocompletePlugins.push(algoliaInsightsDeferredPlugin);
    return autocompletePlugins;
  }
}

// For plugins that may not load immediately, create a wrapper
// plugin and forward events and plugin data once the plugin
// is initialized. This is useful for cases like cookie consent
// which may prevent the analytics insights event plugin from initializing
// immediately.
function deferredLoadPlugin(createPlugin) {
  let plugin = undefined;
  let subscribeObj = undefined;
  const wrappedPlugin = () => {
    if (!plugin && subscribeObj) {
      plugin = createPlugin();
      if (plugin && plugin.subscribe) {
        plugin.subscribe(subscribeObj);
      }
    }
    return plugin;
  };

  return {
    subscribe: (obj) => {
      subscribeObj = obj;
    },
    onStateChange: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onStateChange) {
        plugin.onStateChange(obj);
      }
    },
    onSubmit: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onSubmit) {
        plugin.onSubmit(obj);
      }
    },
    onReset: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onReset) {
        plugin.onReset(obj);
      }
    },
    getSources: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.getSources) {
        return plugin.getSources(obj);
      } else {
        return Promise.resolve([]);
      }
    },
    data: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.data) {
        plugin.data(obj);
      }
    },
  };
}

function validateItems(items) {
  // Validate the first item
  if (items.length > 0) {
    const item = items[0];
    const missingFields = [];
    if (item.href == undefined) {
      missingFields.push("href");
    }
    if (!item.title == undefined) {
      missingFields.push("title");
    }
    if (!item.text == undefined) {
      missingFields.push("text");
    }

    if (missingFields.length === 1) {
      throw {
        name: `Error: Search index is missing the <code>${missingFields[0]}</code> field.`,
        message: `The items being returned for this search do not include all the required fields. Please ensure that your index items include the <code>${missingFields[0]}</code> field or use <code>index-fields</code> in your <code>_quarto.yml</code> file to specify the field names.`,
      };
    } else if (missingFields.length > 1) {
      const missingFieldList = missingFields
        .map((field) => {
          return `<code>${field}</code>`;
        })
        .join(", ");

      throw {
        name: `Error: Search index is missing the following fields: ${missingFieldList}.`,
        message: `The items being returned for this search do not include all the required fields. Please ensure that your index items includes the following fields: ${missingFieldList}, or use <code>index-fields</code> in your <code>_quarto.yml</code> file to specify the field names.`,
      };
    }
  }
}

let lastQuery = null;
function showCopyLink(query, options) {
  const language = options.language;
  lastQuery = query;
  // Insert share icon
  const inputSuffixEl = window.document.body.querySelector(
    ".aa-Form .aa-InputWrapperSuffix"
  );

  if (inputSuffixEl) {
    let copyButtonEl = window.document.body.querySelector(
      ".aa-Form .aa-InputWrapperSuffix .aa-CopyButton"
    );

    if (copyButtonEl === null) {
      copyButtonEl = window.document.createElement("button");
      copyButtonEl.setAttribute("class", "aa-CopyButton");
      copyButtonEl.setAttribute("type", "button");
      copyButtonEl.setAttribute("title", language["search-copy-link-title"]);
      copyButtonEl.onmousedown = (e) => {
        e.preventDefault();
        e.stopPropagation();
      };

      const linkIcon = "bi-clipboard";
      const checkIcon = "bi-check2";

      const shareIconEl = window.document.createElement("i");
      shareIconEl.setAttribute("class", `bi ${linkIcon}`);
      copyButtonEl.appendChild(shareIconEl);
      inputSuffixEl.prepend(copyButtonEl);

      const clipboard = new window.ClipboardJS(".aa-CopyButton", {
        text: function (_trigger) {
          const copyUrl = new URL(window.location);
          copyUrl.searchParams.set(kQueryArg, lastQuery);
          copyUrl.searchParams.set(kResultsArg, "1");
          return copyUrl.toString();
        },
      });
      clipboard.on("success", function (e) {
        // Focus the input

        // button target
        const button = e.trigger;
        const icon = button.querySelector("i.bi");

        // flash "checked"
        icon.classList.add(checkIcon);
        icon.classList.remove(linkIcon);
        setTimeout(function () {
          icon.classList.remove(checkIcon);
          icon.classList.add(linkIcon);
        }, 1000);
      });
    }

    // If there is a query, show the link icon
    if (copyButtonEl) {
      if (lastQuery && options["copy-button"]) {
        copyButtonEl.style.display = "flex";
      } else {
        copyButtonEl.style.display = "none";
      }
    }
  }
}

/* Search Index Handling */
// create the index
var fuseIndex = undefined;
var shownWarning = false;

// fuse index options
const kFuseIndexOptions = {
  keys: [
    { name: "title", weight: 20 },
    { name: "section", weight: 20 },
    { name: "text", weight: 10 },
  ],
  ignoreLocation: true,
  threshold: 0.1,
};

async function readSearchData() {
  // Initialize the search index on demand
  if (fuseIndex === undefined) {
    if (false /* moondata: 索引已内嵌，file:// 下同样可用 */) {
      window.alert(
        "Search requires JavaScript features disabled when running in file://... URLs. In order to use search, please run this document in a web server."
      );
      shownWarning = true;
      return;
    }
    const fuse = new window.Fuse([], kFuseIndexOptions);

    // fetch the main search.json
    const response = __moondataOfflineSearchResponse();
    if (response.status == 200) {
      return response.json().then(function (searchDocs) {
        searchDocs.forEach(function (searchDoc) {
          fuse.add(searchDoc);
        });
        fuseIndex = fuse;
        return fuseIndex;
      });
    } else {
      return Promise.reject(
        new Error(
          "Unexpected status from search index request: " + response.status
        )
      );
    }
  }

  return fuseIndex;
}

function inputElement() {
  return window.document.body.querySelector(".aa-Form .aa-Input");
}

function focusSearchInput() {
  setTimeout(() => {
    const inputEl = inputElement();
    if (inputEl) {
      inputEl.focus();
    }
  }, 50);
}

/* Panels */
const kItemTypeDoc = "document";
const kItemTypeMore = "document-more";
const kItemTypeItem = "document-item";
const kItemTypeError = "error";

function renderItem(
  item,
  createElement,
  state,
  setActiveItemId,
  setContext,
  refresh,
  quartoSearchOptions
) {
  switch (item.type) {
    case kItemTypeDoc:
      return createDocumentCard(
        createElement,
        "file-richtext",
        item.title,
        item.section,
        item.text,
        item.href,
        item.crumbs,
        quartoSearchOptions
      );
    case kItemTypeMore:
      return createMoreCard(
        createElement,
        item,
        state,
        setActiveItemId,
        setContext,
        refresh
      );
    case kItemTypeItem:
      return createSectionCard(
        createElement,
        item.section,
        item.text,
        item.href
      );
    case kItemTypeError:
      return createErrorCard(createElement, item.title, item.text);
    default:
      return undefined;
  }
}

function createDocumentCard(
  createElement,
  icon,
  title,
  section,
  text,
  href,
  crumbs,
  quartoSearchOptions
) {
  const iconEl = createElement("i", {
    class: `bi bi-${icon} search-result-icon`,
  });
  const titleEl = createElement("p", { class: "search-result-title" }, title);
  const titleContents = [iconEl, titleEl];
  const showParent = quartoSearchOptions["show-item-context"];
  if (crumbs && showParent) {
    let crumbsOut = undefined;
    const crumbClz = ["search-result-crumbs"];
    if (showParent === "root") {
      crumbsOut = crumbs.length > 1 ? crumbs[0] : undefined;
    } else if (showParent === "parent") {
      crumbsOut = crumbs.length > 1 ? crumbs[crumbs.length - 2] : undefined;
    } else {
      crumbsOut = crumbs.length > 1 ? crumbs.join(" > ") : undefined;
      crumbClz.push("search-result-crumbs-wrap");
    }

    const crumbEl = createElement(
      "p",
      { class: crumbClz.join(" ") },
      crumbsOut
    );
    titleContents.push(crumbEl);
  }

  const titleContainerEl = createElement(
    "div",
    { class: "search-result-title-container" },
    titleContents
  );

  const textEls = [];
  if (section) {
    const sectionEl = createElement(
      "p",
      { class: "search-result-section" },
      section
    );
    textEls.push(sectionEl);
  }
  const descEl = createElement("p", {
    class: "search-result-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });
  textEls.push(descEl);

  const textContainerEl = createElement(
    "div",
    { class: "search-result-text-container" },
    textEls
  );

  const containerEl = createElement(
    "div",
    {
      class: "search-result-container",
    },
    [titleContainerEl, textContainerEl]
  );

  const linkEl = createElement(
    "a",
    {
      href: offsetURL(href),
      class: "search-result-link",
    },
    containerEl
  );

  const classes = ["search-result-doc", "search-item"];
  if (!section) {
    classes.push("document-selectable");
  }

  return createElement(
    "div",
    {
      class: classes.join(" "),
    },
    linkEl
  );
}

function createMoreCard(
  createElement,
  item,
  state,
  setActiveItemId,
  setContext,
  refresh
) {
  const moreCardEl = createElement(
    "div",
    {
      class: "search-result-more search-item",
      onClick: (e) => {
        // Handle expanding the sections by adding the expanded
        // section to the list of expanded sections
        toggleExpanded(item, state, setContext, setActiveItemId, refresh);
        e.stopPropagation();
      },
    },
    item.title
  );

  return moreCardEl;
}

function toggleExpanded(item, state, setContext, setActiveItemId, refresh) {
  const expanded = state.context.expanded || [];
  if (expanded.includes(item.target)) {
    setContext({
      expanded: expanded.filter((target) => target !== item.target),
    });
  } else {
    setContext({ expanded: [...expanded, item.target] });
  }

  refresh();
  setActiveItemId(item.__autocomplete_id);
}

function createSectionCard(createElement, section, text, href) {
  const sectionEl = createSection(createElement, section, text, href);
  return createElement(
    "div",
    {
      class: "search-result-doc-section search-item",
    },
    sectionEl
  );
}

function createSection(createElement, title, text, href) {
  const descEl = createElement("p", {
    class: "search-result-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });

  const titleEl = createElement("p", { class: "search-result-section" }, title);
  const linkEl = createElement(
    "a",
    {
      href: offsetURL(href),
      class: "search-result-link",
    },
    [titleEl, descEl]
  );
  return linkEl;
}

function createErrorCard(createElement, title, text) {
  const descEl = createElement("p", {
    class: "search-error-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });

  const titleEl = createElement("p", {
    class: "search-error-title",
    dangerouslySetInnerHTML: {
      __html: `<i class="bi bi-exclamation-circle search-error-icon"></i> ${title}`,
    },
  });
  const errorEl = createElement("div", { class: "search-error" }, [
    titleEl,
    descEl,
  ]);
  return errorEl;
}

function positionPanel(pos) {
  const panelEl = window.document.querySelector(
    "#quarto-search-results .aa-Panel"
  );
  const inputEl = window.document.querySelector(
    "#quarto-search .aa-Autocomplete"
  );

  if (panelEl && inputEl) {
    panelEl.style.top = `${Math.round(panelEl.offsetTop)}px`;
    if (pos === "start") {
      panelEl.style.left = `${Math.round(inputEl.left)}px`;
    } else {
      panelEl.style.right = `${Math.round(inputEl.offsetRight)}px`;
    }
  }
}

/* Highlighting */
// highlighting functions
function highlightMatch(query, text) {
  if (text) {
    const start = text.toLowerCase().indexOf(query.toLowerCase());
    if (start !== -1) {
      const startMark = "<mark class='search-match'>";
      const endMark = "</mark>";

      const end = start + query.length;
      text =
        text.slice(0, start) +
        startMark +
        text.slice(start, end) +
        endMark +
        text.slice(end);
      const startInfo = clipStart(text, start);
      const endInfo = clipEnd(
        text,
        startInfo.position + startMark.length + endMark.length
      );
      text =
        startInfo.prefix +
        text.slice(startInfo.position, endInfo.position) +
        endInfo.suffix;

      return text;
    } else {
      return text;
    }
  } else {
    return text;
  }
}

function clipStart(text, pos) {
  const clipStart = pos - 50;
  if (clipStart < 0) {
    // This will just return the start of the string
    return {
      position: 0,
      prefix: "",
    };
  } else {
    // We're clipping before the start of the string, walk backwards to the first space.
    const spacePos = findSpace(text, pos, -1);
    return {
      position: spacePos.position,
      prefix: "",
    };
  }
}

function clipEnd(text, pos) {
  const clipEnd = pos + 200;
  if (clipEnd > text.length) {
    return {
      position: text.length,
      suffix: "",
    };
  } else {
    const spacePos = findSpace(text, clipEnd, 1);
    return {
      position: spacePos.position,
      suffix: spacePos.clipped ? "…" : "",
    };
  }
}

function findSpace(text, start, step) {
  let stepPos = start;
  while (stepPos > -1 && stepPos < text.length) {
    const char = text[stepPos];
    if (char === " " || char === "," || char === ":") {
      return {
        position: step === 1 ? stepPos : stepPos - step,
        clipped: stepPos > 1 && stepPos < text.length,
      };
    }
    stepPos = stepPos + step;
  }

  return {
    position: stepPos - step,
    clipped: false,
  };
}

// removes highlighting as implemented by the mark tag
function clearHighlight(searchterm, el) {
  const childNodes = el.childNodes;
  for (let i = childNodes.length - 1; i >= 0; i--) {
    const node = childNodes[i];
    if (node.nodeType === Node.ELEMENT_NODE) {
      if (
        node.tagName === "MARK" &&
        node.innerText.toLowerCase() === searchterm.toLowerCase()
      ) {
        el.replaceChild(document.createTextNode(node.innerText), node);
      } else {
        clearHighlight(searchterm, node);
      }
    }
  }
}

/** Get all html nodes under the given `root` that don't have children. */
function getLeafNodes(root) {
  let leaves = [];

  function traverse(node) {
    if (node.childNodes.length === 0) {
      leaves.push(node);
    } else {
      node.childNodes.forEach(traverse);
    }
  }

  traverse(root);
  return leaves;
}
/** create and return `<mark>${txt}</mark>` */
const markEl = txt => {
  const el = document.createElement("mark");
  el.appendChild(document.createTextNode(txt));
  return el
}
/** get all ancestors of an element matching the given css selector */
const matchAncestors = (el, selector) => {
  let ancestors = [];
  while (el) {
    if (el.matches?.(selector)) ancestors.push(el);
    el = el.parentNode;
  }
  return ancestors;
};

const isWhitespace = s => s.trim().length === 0
// =================
// MATCHING CODE
// =================
const initMatch = () => ({
  i: 0,
  lohisByNode: new Map()
})
/** 
 * keeps track of the start (lo) and end (hi) index of the match per node (leaf)
 * note: mutates the contents of `matchContext`
 */
const advanceMatch = (leaf, leafi, matchContext) => {
  matchContext.i++

  const curLoHi = matchContext.lohisByNode.get(leaf)

  matchContext.lohisByNode.set(leaf, { lo: curLoHi?.lo ?? leafi, hi: leafi })
}
/**
 * Finds all non-overlapping matches for a search string in the document. 
 * The search string may be split between multiple consecutive leaf nodes.
 * 
 * Whitespace in the search string must be present in the document to match, but
 * there may be addititional whitespace in the document that is ignored.
 * 
 * e.g. searching for `dogs rock` would match `dogs  \n <span> rock</span>`,
 * and would contribute the match 
 * `{ i:9, els: new Map([[textNode, {lo:0, hi:8}],[spanNode,{lo:0,hi:5}]]) }`
 * 
 * @returns {Map<HTMLElement,{lo:number,hi:number}>[]}
 */
function searchMatches(inSearch, el) {
  // searchText has all sequences of whitespace replaced by a single space
  const searchText = inSearch.toLowerCase().replace(/\s+/g, ' ')
  const leafNodes = getLeafNodes(el)

  /** @type {Map<HTMLElement,{lo:number,hi:number}>[]} */
  const matches = []
  /** @type {{i:number; els:Map<HTMLElement,{lo:number,hi:number}>}[]} */
  let curMatchContext = initMatch()

  for (const leaf of leafNodes) {
    const leafStr = leaf.textContent.toLowerCase()
    // for each character in this leaf's text:
    for (let leafi = 0; leafi < leafStr.length; leafi++) {

      if (isWhitespace(leafStr[leafi])) {
        // if there is at least one whitespace in the document
        // we advance over a search text whitespace.
        if (isWhitespace(searchText[curMatchContext.i])) advanceMatch(leaf, leafi, curMatchContext)
        // all sequences of whitespace are otherwise ignored.
      } else {
        if (searchText[curMatchContext.i] === leafStr[leafi]) {
          advanceMatch(leaf, leafi, curMatchContext)
        } else {
          curMatchContext = initMatch()
          // if current character in the document did not match at i in the search text,
          // reset the search and see if that character matches at 0 in the search text.
          if (searchText[curMatchContext.i] === leafStr[leafi]) advanceMatch(leaf, leafi, curMatchContext)
        }
      }

      const isMatchComplete = curMatchContext.i === searchText.length
      if (isMatchComplete) {
        matches.push(curMatchContext.lohisByNode)
        curMatchContext = initMatch()
      }
    }
  }

  return matches
}

/** 
 * e.g. `markMatches(myTextNode, [[0,5],[12,15]])` would wrap the
 * character sequences in myTextNode from 0-5 and 12-15 in marks.
 * Its important to mark all sequences in a text node at once
 * because this function replaces the entire text node; so any
 * other references to that text node will no longer be in the DOM.
 */
function markMatches(node, lohis) {
  const text = node.nodeValue

  const markFragment = document.createDocumentFragment();

  let prevHi = 0
  for (const [lo, hi] of lohis) {
    markFragment.append(
      document.createTextNode(text.slice(prevHi, lo)),
      markEl(text.slice(lo, hi + 1))
    )
    prevHi = hi + 1
  }
  markFragment.append(
    document.createTextNode(text.slice(prevHi, text.length))
  )

  const parent = node.parentElement
  parent?.replaceChild(markFragment, node)
  return parent
}

// Activate ancestor tabs so a search match inside an inactive pane becomes visible.
// When multiple panes in the same tabset contain matches, avoid switching away from
// the currently active pane — the user already sees a match there.
function openAllTabsetsContainingEl(el) {
  for (const pane of matchAncestors(el, '.tab-pane')) {
    const tabContent = pane.closest('.tab-content');
    if (!tabContent) continue;
    const activePane = tabContent.querySelector(':scope > .tab-pane.active');
    if (activePane?.querySelector('mark')) continue;
    const tabButton = document.querySelector(`[data-bs-target="#${pane.id}"]`);
    if (tabButton) new bootstrap.Tab(tabButton).show();
  }
}

function scrollToFirstVisibleMatch(mainEl) {
  for (const mark of mainEl.querySelectorAll("mark")) {
    const isMarkVisible = matchAncestors(mark, '.tab-pane').every(markTabPane =>
      markTabPane.classList.contains("active")
    )
    if (isMarkVisible) {
      mark.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
  }
}

/**
 * e.g.
 * ```js
 * const m = new Map()
 *
 * arrayMapPush(m, 'dog', 'Max')
 * console.log(m) // Map { dog->['Max'] }
 * 
 * arrayMapPush(m, 'dog', 'Samba')
 * arrayMapPush(m, 'cat', 'Scruffle')
 * console.log(m) // Map { dog->['Max', 'Samba'], cat->['Scruffle'] }
 * ```
 */
const arrayMapPush = (map, key, item) => {
  if (!map.has(key)) map.set(key, [])
  map.set(key, [...map.get(key), item])
}

// copy&paste any string from a quarto page and
// this should find that string in the page and highlight it.
// exception: text that starts outside/inside a tabset and ends
// inside/outside that tabset. 
function highlight(searchStr, el) {
  const matches = searchMatches(searchStr, el);

  const matchesGroupedByNode = new Map()
  for (const match of matches) {
    for (const [mel, { lo, hi }] of match) {
      arrayMapPush(matchesGroupedByNode, mel, [lo, hi])
    }
  }

  for (const [node, lohis] of matchesGroupedByNode) {
    markMatches(node, lohis)
  }
}

/* Link Handling */
// get the offset from this page for a given site root relative url
function offsetURL(url) {
  var offset = getMeta("quarto:offset");
  return offset ? offset + url : url;
}

// read a meta tag value
function getMeta(metaName) {
  var metas = window.document.getElementsByTagName("meta");
  for (let i = 0; i < metas.length; i++) {
    if (metas[i].getAttribute("name") === metaName) {
      return metas[i].getAttribute("content");
    }
  }
  return "";
}

function algoliaSearch(query, limit, algoliaOptions) {
  const { getAlgoliaResults } = window["@algolia/autocomplete-preset-algolia"];

  const applicationId = algoliaOptions["application-id"];
  const searchOnlyApiKey = algoliaOptions["search-only-api-key"];
  const indexName = algoliaOptions["index-name"];
  const indexFields = algoliaOptions["index-fields"];
  const searchClient = window.algoliasearch(applicationId, searchOnlyApiKey);
  const searchParams = algoliaOptions["params"];
  const searchAnalytics = !!algoliaOptions["analytics-events"];

  return getAlgoliaResults({
    searchClient,
    queries: [
      {
        indexName: indexName,
        query,
        params: {
          hitsPerPage: limit,
          clickAnalytics: searchAnalytics,
          ...searchParams,
        },
      },
    ],
    transformResponse: (response) => {
      if (!indexFields) {
        return response.hits.map((hit) => {
          return hit.map((item) => {
            return {
              ...item,
              text: highlightMatch(query, item.text),
            };
          });
        });
      } else {
        const remappedHits = response.hits.map((hit) => {
          return hit.map((item) => {
            const newItem = { ...item };
            ["href", "section", "title", "text", "crumbs"].forEach(
              (keyName) => {
                const mappedName = indexFields[keyName];
                if (
                  mappedName &&
                  item[mappedName] !== undefined &&
                  mappedName !== keyName
                ) {
                  newItem[keyName] = item[mappedName];
                  delete newItem[mappedName];
                }
              }
            );
            newItem.text = highlightMatch(query, newItem.text);
            return newItem;
          });
        });
        return remappedHits;
      }
    },
  });
}

let subSearchTerm = undefined;
let subSearchFuse = undefined;
const kFuseMaxWait = 125;

async function fuseSearch(query, fuse, fuseOptions) {
  let index = fuse;
  // Fuse.js using the Bitap algorithm for text matching which runs in
  // O(nm) time (no matter the structure of the text). In our case this
  // means that long search terms mixed with large index gets very slow
  //
  // This injects a subIndex that will be used once the terms get long enough
  // Usually making this subindex is cheap since there will typically be
  // a subset of results matching the existing query
  if (subSearchFuse !== undefined && query.startsWith(subSearchTerm)) {
    // Use the existing subSearchFuse
    index = subSearchFuse;
  } else if (subSearchFuse !== undefined) {
    // The term changed, discard the existing fuse
    subSearchFuse = undefined;
    subSearchTerm = undefined;
  }

  // Search using the active fuse
  const then = performance.now();
  const resultsRaw = await index.search(query, fuseOptions);
  const now = performance.now();

  const results = resultsRaw.map((result) => {
    const addParam = (url, name, value) => {
      const anchorParts = url.split("#");
      const baseUrl = anchorParts[0];
      const sep = baseUrl.search("\\?") > 0 ? "&" : "?";
      anchorParts[0] = baseUrl + sep + name + "=" + value;
      return anchorParts.join("#");
    };

    return {
      title: result.item.title,
      section: result.item.section,
      href: addParam(result.item.href, kQueryArg, query),
      text: highlightMatch(query, result.item.text),
      crumbs: result.item.crumbs,
    };
  });

  // If we don't have a subfuse and the query is long enough, go ahead
  // and create a subfuse to use for subsequent queries
  if (
    now - then > kFuseMaxWait &&
    subSearchFuse === undefined &&
    resultsRaw.length < fuseOptions.limit
  ) {
    subSearchTerm = query;
    subSearchFuse = new window.Fuse([], kFuseIndexOptions);
    resultsRaw.forEach((rr) => {
      subSearchFuse.add(rr.item);
    });
  }
  return results;
}

/* >>> moondata:offline-search-index —— 由 moondata.docsite 生成，勿手改 */
const __moondataSearchDocuments = [{"objectID": "docs/dataset-study.html", "href": "docs/dataset-study.html", "title": "数据集特性研究", "section": "", "text": "注记这一部分现在是空的，而且是有意空着的\n\n\n\n本轮（issue #4）只在导航里为它留一个位置，不产出任何内容。 下面写的是将来往这里放什么、以什么形式放，不是结论。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "docs/dataset-study.html#将来放什么", "href": "docs/dataset-study.html#将来放什么", "title": "数据集特性研究", "section": "将来放什么", "text": "将来放什么\n数据集本身的性质问题——不是「它怎么被做出来的」（那是流程文档），而是 「它是什么样的、有什么毛病、某个现象为什么会这样」。已经知道存在、但本轮明确不碰的， 例如：若干 ROI 的局部错位、若干 ROI 的 SAR 距离向有效分辨率异常、 窗口清单与实际产物的数量差、部分 ROI 是否残留旧的重采样网纹。\n人工标注的质量至今没有评估过。这是将来必做的一项，本轮完全不碰—— 在它做完之前，任何基于评测真值点得出的精度数字都建立在一个未经检验的前提上。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "docs/dataset-study.html#以什么形式放", "href": "docs/dataset-study.html#以什么形式放", "title": "数据集特性研究", "section": "以什么形式放", "text": "以什么形式放\n一个问题一篇，笔记式，不预先搭章节结构。每篇包含问题、证据、结论， 并且保留已经被证伪的假设：走过的死路和它为什么是死路，与结论同样值得写下来， 否则接手的人会把同一条路再走一遍。\n之所以不在这里先摆出一排空标题，是因为章节结构会反过来规定研究该往哪走。 等真有了第一篇再谈结构。\n笔记可以是 .qmd，也可以直接是 .ipynb——Quarto 两种都能渲染成站点的一页， 不需要为此改工具链。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "index.html", "href": "index.html", "title": "月球光学–SAR 配准数据集", "section": "", "text": "这里是这个数据集的全部说明材料。数据集已经冻结，955 GB 影像不在仓库里； 这个站点要回答的是：它是什么、从哪来、怎么被做成这样、以及你拿到的是什么。", "crumbs": ["首页"]}, {"objectID": "index.html#怎么读", "href": "index.html#怎么读", "title": "月球光学–SAR 配准数据集", "section": "怎么读", "text": "怎么读\n什么都不用装。 站点的构建产物随仓库一起提交，克隆下来双击 _site/index.html 就能看——不需要 Python、不需要 Quarto、不需要联网，也不需要接那块移动硬盘。\n左边是导航树，右边是本页目录，右上角的搜索框搜全站正文（中文可用）。\n\n\n\n\n\n\n提示第一次来，先读术语表\n\n\n\n尤其是对齐控制点与评测真值点的区别，以及坐标符号约定。 前者错了会让评测结论失效，后者错了会让配准结果整体镜像——而且两种错误都不报错。", "crumbs": ["首页"]}, {"objectID": "index.html#数据集是怎么来的", "href": "index.html#数据集是怎么来的", "title": "月球光学–SAR 配准数据集", "section": "数据集是怎么来的", "text": "数据集是怎么来的\n\n\n\n\n\nflowchart LR\n  A[\"① 算重叠区&lt;br/&gt;光学 ∩ SAR\"] --&gt; B[\"② 标对齐控制点&lt;br/&gt;人工，ENVI\"]\n  B --&gt; C[\"③ 估计全局变换&lt;br/&gt;每 ROI 一个\"]\n  C --&gt; D[\"④ 正向算窗口&lt;br/&gt;切 patch\"]\n  B -.-&gt; E[[\"不可再生&lt;br/&gt;已入库 data/\"]]\n  D --&gt; F[\"数据集&lt;br/&gt;67 个 ROI\"]\n\n\n\n\n\n\n第 ② 步是人工的，无法自动复现，所以那批标注被当作数据纳入版本控制 （仓库里的 data/README.md）。 其余三步要求正向计算：不读任何历史产物的位置信息，独立算出与现有数据集一致的结果。\n代码的顶层模块与这四步一一对应，所以目录结构本身就是上面这张图。", "crumbs": ["首页"]}, {"objectID": "index.html#站点里有什么", "href": "index.html#站点里有什么", "title": "月球光学–SAR 配准数据集", "section": "站点里有什么", "text": "站点里有什么\n\n\n\n\n内容\n状态\n\n\n\n\n术语表\n词汇与坐标符号约定\n本轮产出\n\n\n来源文档\n数据从哪来：官方产品、投影、波段\n尚未产出（issue #7）\n\n\n流程文档\n它如何被做成这样\n尚未产出（issue #11）\n\n\n产物文档\n你拿到的是什么：目录、命名、数量\n尚未产出（issue #5）\n\n\n数据集特性研究\n一个问题一篇的研究笔记\n本轮不产出，仅留位\n\n\n\n文档里将来出现的统计数字都从统计快照取值，不手写——快照由扫描脚本从真实数据生成， 所以数字不会在无人察觉时过期。", "crumbs": ["首页"]}, {"objectID": "index.html#怎么重新构建", "href": "index.html#怎么重新构建", "title": "月球光学–SAR 配准数据集", "section": "怎么重新构建", "text": "怎么重新构建\nquarto render\n一条命令，产出提交到 _site/。改完 .qmd 记得重跑一次，否则读者看到的还是旧的。", "crumbs": ["首页"]}, {"objectID": "CONTEXT.html", "href": "CONTEXT.html", "title": "术语表", "section": "", "text": "本文件是本项目的词汇表：每条只给定义与中英对照，不讲实现、不给操作步骤、 不放统计数字。要知道数据从哪来、怎么被做成这样、最终长什么样，看主体文档。\n词汇表放在仓库根而不是只放在文档站里，是因为它同时服务两类读者：读文档站的人， 以及只有一个终端、正要动手改代码的人（含 agent）。两边看到的是同一份文件—— 文档站里的这一页就是 CONTEXT.md 本身渲染出来的，不存在第二份会漂的副本。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#影像与区域", "href": "CONTEXT.html#影像与区域", "title": "术语表", "section": "影像与区域", "text": "影像与区域\n\nROI（region of interest，感兴趣区）\n一块光学与 SAR 同时覆盖的月表区域，是本数据集的组织单位。编号形如 ROI_35。 每个 ROI 有自己的一对对齐影像、一套对齐控制点、一批 patch。\n\n\n光学影像（optical image）\n嫦娥二号（CE-2）7 m 分辨率数字正射影像（DOM）。单波段，8 位无符号整型。\n\n\nSAR 影像（SAR image）\nMini-RF 雷达影像。四波段，32 位浮点，含负值。\n\n\n对齐影像（aligned image）\n一个 ROI 的光学与 SAR 被重采样到同一网格后的那一对大图。patch 从它上面切出来， 对齐控制点也标在它上面。\n\n\npatch（切片）\n从对齐影像上按固定尺寸切下来的小图，光学与 SAR 一一对应，同编号即同一块地面。 它是数据集对外交付的最小单位，也是评测真值点唯一存在的地方。 中文里不译，沿用 patch——既有代码、目录名与文件名全都是这个词。\n\n\n划分（split）\nTrain / Val / Test，按 ROI 划分，不按 patch 划分：同一个 ROI 的全部 patch 落在同一个划分里。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#两种同名点这两条必须分清", "href": "CONTEXT.html#两种同名点这两条必须分清", "title": "术语表", "section": "两种同名点（这两条必须分清）", "text": "两种同名点（这两条必须分清）\n「同名点」（tie point / corresponding point）指一对指向同一地物的坐标——一个在光学上， 一个在 SAR 上。本项目里有两批同名点，它们的标注位置、数量级、覆盖范围和用途 完全不同，混用会直接导致错误结论。\n\n对齐控制点（alignment tie points）\n\n标在哪 —— 人工在 ENVI 中于对齐影像（整幅大图）上标注。\n多少 —— 每个 ROI 约 30 对。\n覆盖 —— 全部 67 个 ROI，三个划分都有。\n用途 —— 求解该 ROI 的全局变换，进而决定 patch 切在哪。它是生产资料。\n不是什么 —— 不是评测的金标准。拿它去评测，等于用造数据的那把尺子量数据自己。\n\n\n\n评测真值点（evaluation ground truth）\n\n标在哪 —— 人工在单个 patch 上标注。\n多少 —— 每个 patch 约 8 对。\n覆盖 —— 只存在于验证集与测试集，且只覆盖其中约 82% 的 patch； 训练集完全没有。\n用途 —— 评测配准算法的精度。它是评测基准。\n\n\n\n为什么按用途命名\n这两批点在既有代码与文件名里被叫作 tie 和 label，口头上则常被称作「大图上的点」 与「小图上的点」。文档一律使用上面两个专名，因为按位置命名解释不了 「训练集为什么没有后者」，而按用途命名，答案自明：训练集不需要被评测。\n文件名与文件格式保持现状不改——它们是格式契约，既有数据和既有代码都按它读写。 改的只是我们讲话时用的词。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#坐标符号约定coordinate-sign-convention", "href": "CONTEXT.html#坐标符号约定coordinate-sign-convention", "title": "术语表", "section": "坐标符号约定（coordinate sign convention）", "text": "坐标符号约定（coordinate sign convention）\n\n\n\n\n\n\n重要弄错了不会报错，只会算出镜像的结果\n\n\n\n三种同名点文件对 y 的符号处理不一致，而三者都是纯文本的数字列。取错符号的产物 在数值上完全正常、打开看也完全正常，只有配准结果整体沿水平轴翻转——没有任何一步 会抛异常。这是本项目最容易静默出错的地方，所以它被钉进词汇表。\n\n\n\n\n\n文件\n内容\n坐标\ny 的符号\n\n\n\n\nLabel/patch_&lt;n&gt;.txt\n评测真值点\npatch 内像素\n取负\n\n\ncropped/opt_tie.pts\n对齐控制点\n对齐影像像素\n不取负\n\n\ncropped/opt_tie.txt\n对齐控制点\n地图坐标（米）\n不取负\n\n\n\n约定：包内一律用不取负的 y（向下为正的像素行号），取负只是标签文件的磁盘格式。 因此符号转换只发生在读写边界——读标签文件时取一次负，写标签文件时再取一次负， 中间所有计算、所有内存中的数组，y 都是正的。任何在中途翻符号的代码都是错的。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#复现与验收", "href": "CONTEXT.html#复现与验收", "title": "术语表", "section": "复现与验收", "text": "复现与验收\n\n窗口（window）\n一个 patch 在对齐影像上的位置，记作左上角像素坐标加固定的 patch 尺寸。 「算窗口」与「切 patch」是两件事：前者不读影像，后者要。\n\n\n窗口清单（window manifest）\ndata/windows/ 下逐 ROI 记录网格与全部窗口坐标的 JSON。\n它的用途发生过一次转变：最初是从已有 patch 反推出来的，为的是重切之后 「网格、窗口、编号」三者不变，从而让 patch 上的评测真值点继续成立；现在它是 正向复现的验收基准——新代码正向算出的窗口必须与它逐条相等。同一份文件， 两种截然不同的用途。\n\n\n正向复现（forward reproduction）\n从原始输入与对齐控制点独立算出现有数据集，不读取任何历史产物的位置信息。 这是本项目对代码的核心要求，也是「第二版代码读着旧 patch 反推着切」这一做法被废弃的原因。\n\n\n一级验收 / 二级验收（level-1 / level-2 acceptance）\n\n一级：正向算出的窗口与窗口清单逐条相等。不读影像，快。\n二级：切出的 patch 与现有产物逐字节一致。要读影像，慢。\n\n\n\n冻结（frozen）\n验证集与测试集不再重切。原因是人工标注的评测真值点会随重切而作废， 不是数据本身有问题。训练集不受这条约束——它没有评测真值点，没有什么会作废。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#工作区", "href": "CONTEXT.html#工作区", "title": "术语表", "section": "工作区", "text": "工作区\n\n数据根（data root）\n955 GB 影像所在目录的本机路径。影像不进仓库，靠它引用；不同机器挂载点不同， 所以它可配置（--data-root → MOONDATA_DATA_ROOT → moondata.toml，取第一个非空的）。\n\n\n统计快照（statistics snapshot）\nstats/snapshot.json。从真实数据扫描出来的统计量，携带生成时间与一枚数据指纹。 文档只读快照，不读影像——所以移动硬盘没插时文档照样渲染。\n\n\n数据指纹（data fingerprint）\n刻画数据根目录形态（相对路径 + 文件大小）的摘要，不是像素内容的哈希。 它回答的是「快照还作不作数」。", "crumbs": ["首页", "术语表"]}];
function __moondataOfflineSearchResponse() {
  return {
    status: 200,
    json: function () {
      return Promise.resolve(__moondataSearchDocuments);
    },
  };
}
/* <<< moondata:offline-search-index */
